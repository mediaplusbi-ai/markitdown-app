import os
import tempfile
import shutil
import json
import threading
import logging
from flask import Flask, request, jsonify, render_template
from markitdown import MarkItDown
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge, HTTPException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # 25MB per chunk

ALLOWED_EXTENSIONS = {
    'pdf', 'docx', 'doc', 'pptx', 'ppt',
    'xlsx', 'xls', 'csv', 'json', 'xml',
    'html', 'htm', 'txt', 'md', 'epub', 'zip'
}

CHUNKS_BASE = os.path.join(tempfile.gettempdir(), 'markitdown_chunks')

# Job results store: { job_id: { status, result, error } }
JOB_STORE = {}

@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(e):
    return jsonify({'error': 'Chunk too large — maximum chunk size is 25 MB'}), 413

@app.errorhandler(HTTPException)
def handle_http_exception(e):
    return jsonify({'error': f'{e.code} {e.name}: {e.description}'}), e.code

@app.errorhandler(Exception)
def handle_exception(e):
    logger.exception("Unhandled exception")
    return jsonify({'error': str(e)}), 500

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload-chunk', methods=['POST'])
def upload_chunk():
    upload_id    = request.form.get('upload_id')
    chunk_index  = request.form.get('chunk_index')
    total_chunks = request.form.get('total_chunks')
    filename     = secure_filename(request.form.get('filename', ''))
    chunk_file   = request.files.get('chunk')

    if not all([upload_id, chunk_index is not None, total_chunks, chunk_file, filename]):
        return jsonify({'error': 'Missing parameters'}), 400
    if not allowed_file(filename):
        return jsonify({'error': 'File type not supported'}), 400

    chunk_index  = int(chunk_index)
    total_chunks = int(total_chunks)

    chunk_dir = os.path.join(CHUNKS_BASE, upload_id)
    os.makedirs(chunk_dir, exist_ok=True)
    chunk_file.save(os.path.join(chunk_dir, f'chunk_{chunk_index:05d}'))

    meta_path = os.path.join(chunk_dir, 'meta.json')
    if not os.path.exists(meta_path):
        with open(meta_path, 'w') as f:
            json.dump({'total': total_chunks, 'filename': filename}, f)

    return jsonify({'received': chunk_index, 'total': total_chunks})


def _do_conversion(job_id, chunk_dir, total, filename):
    """Runs in a background thread — reassembles chunks and converts."""
    suffix   = '.' + filename.rsplit('.', 1)[1].lower()
    tmp_path = None
    try:
        JOB_STORE[job_id] = {'status': 'converting'}

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            for i in range(total):
                chunk_path = os.path.join(chunk_dir, f'chunk_{i:05d}')
                with open(chunk_path, 'rb') as cf:
                    tmp.write(cf.read())

        logger.info(f"[{job_id}] Reassembled {total} chunks → {tmp_path}")

        md     = MarkItDown()
        result = md.convert(tmp_path)
        text   = result.text_content or ''

        JOB_STORE[job_id] = {
            'status':   'done',
            'markdown': text,
            'chars':    len(text),
            'tokens':   len(text) // 4,
            'filename': filename,
        }
        logger.info(f"[{job_id}] Conversion done — {len(text)} chars")

    except Exception as e:
        logger.exception(f"[{job_id}] Conversion failed")
        JOB_STORE[job_id] = {'status': 'error', 'error': str(e)}

    finally:
        if tmp_path:
            try: os.unlink(tmp_path)
            except: pass
        shutil.rmtree(chunk_dir, ignore_errors=True)


@app.route('/convert-chunks', methods=['POST'])
def convert_chunks():
    data      = request.get_json()
    upload_id = data.get('upload_id') if data else None

    if not upload_id:
        return jsonify({'error': 'Missing upload_id'}), 400

    chunk_dir = os.path.join(CHUNKS_BASE, upload_id)
    meta_path = os.path.join(chunk_dir, 'meta.json')

    if not os.path.exists(meta_path):
        return jsonify({'error': 'Upload session not found — please re-upload'}), 400

    with open(meta_path) as f:
        meta = json.load(f)

    total    = meta['total']
    filename = meta['filename']

    missing = [i for i in range(total)
               if not os.path.exists(os.path.join(chunk_dir, f'chunk_{i:05d}'))]
    if missing:
        return jsonify({'error': f'Missing chunks: {missing}'}), 400

    job_id = upload_id  # reuse same ID
    JOB_STORE[job_id] = {'status': 'queued'}

    t = threading.Thread(target=_do_conversion,
                         args=(job_id, chunk_dir, total, filename),
                         daemon=True)
    t.start()

    return jsonify({'job_id': job_id, 'status': 'queued'})


@app.route('/job-status/<job_id>', methods=['GET'])
def job_status(job_id):
    job = JOB_STORE.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(job)


@app.route('/convert', methods=['POST'])
def convert():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not supported'}), 400

    try:
        filename = secure_filename(file.filename)
        suffix   = '.' + filename.rsplit('.', 1)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name
        md     = MarkItDown()
        result = md.convert(tmp_path)
        text   = result.text_content or ''
        os.unlink(tmp_path)
        return jsonify({
            'markdown': text,
            'chars':    len(text),
            'tokens':   len(text) // 4,
            'filename': filename,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)