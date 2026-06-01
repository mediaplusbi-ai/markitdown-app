import os
import tempfile
import shutil
import json
from flask import Flask, request, jsonify, render_template
from markitdown import MarkItDown
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge, HTTPException

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # 25MB per chunk

ALLOWED_EXTENSIONS = {
    'pdf', 'docx', 'doc', 'pptx', 'ppt',
    'xlsx', 'xls', 'csv', 'json', 'xml',
    'html', 'htm', 'txt', 'md', 'epub', 'zip'
}

CHUNKS_BASE = os.path.join(tempfile.gettempdir(), 'markitdown_chunks')

@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(e):
    return jsonify({'error': 'Chunk too large — maximum chunk size is 25 MB'}), 413

@app.errorhandler(HTTPException)
def handle_http_exception(e):
    return jsonify({'error': f'{e.code} {e.name}: {e.description}'}), e.code

@app.errorhandler(Exception)
def handle_exception(e):
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

    # Save chunk to disk
    chunk_dir = os.path.join(CHUNKS_BASE, upload_id)
    os.makedirs(chunk_dir, exist_ok=True)
    chunk_file.save(os.path.join(chunk_dir, f'chunk_{chunk_index:05d}'))

    # Save metadata to disk (not memory)
    meta_path = os.path.join(chunk_dir, 'meta.json')
    if not os.path.exists(meta_path):
        with open(meta_path, 'w') as f:
            json.dump({'total': total_chunks, 'filename': filename}, f)

    return jsonify({'received': chunk_index, 'total': total_chunks})


@app.route('/convert-chunks', methods=['POST'])
def convert_chunks():
    data      = request.get_json()
    upload_id = data.get('upload_id') if data else None

    if not upload_id:
        return jsonify({'error': 'Missing upload_id'}), 400

    chunk_dir = os.path.join(CHUNKS_BASE, upload_id)
    meta_path = os.path.join(chunk_dir, 'meta.json')

    if not os.path.exists(meta_path):
        return jsonify({'error': 'Upload session not found — please try again'}), 400

    with open(meta_path) as f:
        meta = json.load(f)

    total    = meta['total']
    filename = meta['filename']

    # Verify all chunks are on disk
    missing = [i for i in range(total) if not os.path.exists(os.path.join(chunk_dir, f'chunk_{i:05d}'))]
    if missing:
        return jsonify({'error': f'Missing chunks: {missing}'}), 400

    suffix   = '.' + filename.rsplit('.', 1)[1].lower()
    tmp_path = None

    try:
        # Reassemble
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            for i in range(total):
                with open(os.path.join(chunk_dir, f'chunk_{i:05d}'), 'rb') as cf:
                    tmp.write(cf.read())

        # Convert
        md     = MarkItDown()
        result = md.convert(tmp_path)
        text   = result.text_content or ''

        return jsonify({
            'markdown': text,
            'chars':    len(text),
            'tokens':   len(text) // 4,
            'filename': filename
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

    finally:
        if tmp_path:
            try: os.unlink(tmp_path)
            except: pass
        shutil.rmtree(chunk_dir, ignore_errors=True)


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
            'filename': filename
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)