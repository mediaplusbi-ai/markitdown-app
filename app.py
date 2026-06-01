import os
import tempfile
from flask import Flask, request, jsonify, render_template
from markitdown import MarkItDown
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max

ALLOWED_EXTENSIONS = {
    'pdf', 'docx', 'doc', 'pptx', 'ppt',
    'xlsx', 'xls', 'csv', 'json', 'xml',
    'html', 'htm', 'txt', 'md', 'epub', 'zip'
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
