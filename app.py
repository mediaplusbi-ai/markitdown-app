import os
import tempfile
import shutil
from flask import Flask, request, jsonify, render_template
from markitdown import MarkItDown
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # 25MB per chunk request (safety margin)

from werkzeug.exceptions import RequestEntityTooLarge, HTTPException

@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(e):
    return jsonify({'error': 'Chunk too large — maximum chunk size is 25 MB'}), 413

@app.errorhandler(HTTPException)
def handle_http_exception(e):
    return jsonify({'error': f'{e.code} {e.name}: {e.description}'}), e.code

@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({'error': str(e)}), 500

ALLOWED_EXTENSIONS = {
    'pdf', 'docx', 'doc', 'pptx', 'ppt',
    'xlsx', 'xls', 'csv', 'json', 'xml',
    'html', 'htm', 'txt', 'md', 'epub', 'zip'
}

# Temp storage for chunks: { upload_id: { 'chunks': {index: path}, 'total': N, 'filename': str } }
CHUNK_STORE = {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload-chunk', methods=['POST'])
def upload_chunk():
    """Receive one chunk and store it temporarily."""
    upload_id  = request.form.get('upload_id')
    chunk_index = int(request.form.get('chunk_index'))
    total_chunks = int(request.form.get('total_chunks'))
    filename    = secure_filename(request.form.get('filename', ''))
    chunk_file  = request.files.get('chunk')

    if not all([upload_id, chunk_file, filename]):
        return jsonify({'error': 'Missing parameters'}), 400

    if not allowed_file(filename):
        return jsonify({'error': 'File type not supported'}), 400

    # Save chunk to a temp file
    chunk_dir = os.path.join(tempfile.gettempdir(), 'markitdown_chunks', upload_id)
    os.makedirs(chunk_dir, exist_ok=True)
    chunk_path = os.path.join(chunk_dir, f'chunk_{chunk_index}')
    chunk_file.save(chunk_path)

    if upload_id not in CHUNK_STORE:
        CHUNK_STORE[upload_id] = {'chunks': {}, 'total': total_chunks, 'filename': filename}
    CHUNK_STORE[upload_id]['chunks'][chunk_index] = chunk_path

    return jsonify({'received': chunk_index, 'total': total_chunks})


@app.route('/convert-chunks', methods=['POST'])
def convert_chunks():
    """Reassemble chunks and convert to markdown."""
    data = request.get_json()
    upload_id = data.get('upload_id')

    if not upload_id or upload_id not in CHUNK_STORE:
        return jsonify({'error': 'Invalid or expired upload session'}), 400

    store = CHUNK_STORE[upload_id]
    total = store['total']
    filename = store['filename']
    chunks = store['chunks']

    if len(chunks) != total:
        return jsonify({'error': f'Missing chunks: got {len(chunks)}/{total}'}), 400

    suffix = '.' + filename.rsplit('.', 1)[1].lower()

    try:
        # Reassemble file
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            for i in range(total):
                with open(chunks[i], 'rb') as cf:
                    tmp.write(cf.read())

        # Convert
        md = MarkItDown()
        result = md.convert(tmp_path)
        text = result.text_content or ''

        char_count = len(text)
        token_estimate = char_count // 4

        return jsonify({
            'markdown': text,
            'chars': char_count,
            'tokens': token_estimate,
            'filename': filename
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

    finally:
        # Cleanup
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        chunk_dir = os.path.join(tempfile.gettempdir(), 'markitdown_chunks', upload_id)
        shutil.rmtree(chunk_dir, ignore_errors=True)
        CHUNK_STORE.pop(upload_id, None)


# Keep old /convert for backward compat (small files under 10MB)
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
        suffix = '.' + filename.rsplit('.', 1)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name
        md = MarkItDown()
        result = md.convert(tmp_path)
        text = result.text_content or ''
        os.unlink(tmp_path)
        return jsonify({
            'markdown': text,
            'chars': len(text),
            'tokens': len(text) // 4,
            'filename': filename
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)