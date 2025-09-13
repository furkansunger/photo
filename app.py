# app.py - Fotoğraf İşleme Backend Servisi
import os
import io
import zipfile
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from PIL import Image, ImageDraw
from rembg import remove
from werkzeug.utils import secure_filename
import base64
from datetime import datetime
import shutil

app = Flask(__name__)
CORS(app)  # CORS'u etkinleştir

# Klasör yapısını oluştur
UPLOAD_FOLDER = 'uploads'
PROCESSED_FOLDER = 'processed'
WATERMARK_FOLDER = 'watermarks'
STATIC_FOLDER = 'static'

for folder in [UPLOAD_FOLDER, PROCESSED_FOLDER, WATERMARK_FOLDER, STATIC_FOLDER]:
    os.makedirs(folder, exist_ok=True)

app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size

class PhotoProcessor:
    """Fotoğraf işleme sınıfı"""
    
    def __init__(self):
        self.processed_count = 0
        self.error_count = 0
        
    def remove_background(self, image_path):
        """Arka planı kaldır"""
        try:
            with open(image_path, 'rb') as img_file:
                input_image = img_file.read()
            
            # Rembg ile arka planı kaldır
            output = remove(input_image)
            
            # PIL Image objesine çevir
            img = Image.open(io.BytesIO(output))
            return img
        except Exception as e:
            print(f"Arka plan kaldırma hatası: {e}")
            # Hata durumunda orijinal görüntüyü döndür
            return Image.open(image_path)
    
    def add_white_background(self, img):
        """Beyaz arka plan ekle"""
        # RGBA modunda ise beyaz arka plan ekle
        if img.mode in ('RGBA', 'LA'):
            # Beyaz arka plan oluştur
            background = Image.new('RGB', img.size, (255, 255, 255))
            
            # Alpha kanalını kullanarak yapıştır
            if img.mode == 'RGBA':
                background.paste(img, mask=img.split()[3])  # Alpha kanalı
            else:
                background.paste(img, mask=img.split()[1])  # LA modu için
                
            return background
        
        # RGB modunda ise direkt döndür
        return img.convert('RGB')
    
    def resize_image(self, img, max_width, max_height):
        """Görseli orantılı olarak yeniden boyutlandır"""
        # Orijinal boyutlar
        width, height = img.size
        
        # Oran hesaplama
        width_ratio = max_width / width if width > max_width else 1
        height_ratio = max_height / height if height > max_height else 1
        
        # En küçük oranı kullan (orantıyı korumak için)
        ratio = min(width_ratio, height_ratio)
        
        if ratio < 1:
            new_width = int(width * ratio)
            new_height = int(height * ratio)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        return img
    
    def add_watermark(self, img, watermark_path, position='bottom-right', opacity=50):
        """Görsel filigran ekle"""
        if not watermark_path or not os.path.exists(watermark_path):
            return img
        
        try:
            # Filigranı yükle
            watermark = Image.open(watermark_path)
            
            # Filigranı RGBA moduna çevir
            if watermark.mode != 'RGBA':
                watermark = watermark.convert('RGBA')
            
            # Filigran boyutunu ayarla (ana görüntünün %60'ı kadar)
            img_width, img_height = img.size
            watermark_width = int(img_width * 0.6)
            watermark_ratio = watermark_width / watermark.width
            watermark_height = int(watermark.height * watermark_ratio)
            watermark = watermark.resize((watermark_width, watermark_height), Image.Resampling.LANCZOS)
            
            # Opaklığı ayarla
            if opacity < 100:
                # Alpha kanalını ayarla
                alpha = watermark.split()[3]
                alpha = alpha.point(lambda p: p * (opacity / 100))
                watermark.putalpha(alpha)
            
            # Pozisyon hesaplama
            margin = 20
            if position == 'bottom-right':
                x = img_width - watermark_width - margin
                y = img_height - watermark_height - margin
            elif position == 'bottom-left':
                x = margin
                y = img_height - watermark_height - margin
            elif position == 'top-right':
                x = img_width - watermark_width - margin
                y = margin
            elif position == 'top-left':
                x = margin
                y = margin
            else:  # center
                x = (img_width - watermark_width) // 2
                y = (img_height - watermark_height) // 2
            
            # Ana görüntüyü RGBA'ya çevir
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            
            # Filigranı yapıştır
            img.paste(watermark, (x, y), watermark)
            
            # RGB'ye geri çevir
            img = img.convert('RGB')
            
        except Exception as e:
            print(f"Filigran ekleme hatası: {e}")
        
        return img
    
    def generate_filename(self, original_name, index, brand_name='', model_name='', project_number=''):
        """Yeni dosya adı oluştur"""
        ext = os.path.splitext(original_name)[1]
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Filename parçalarını birleştir
        filename_parts = []
        
        if brand_name:
            filename_parts.append(brand_name)
        
        if model_name:
            filename_parts.append(model_name)
            
        if project_number:
            filename_parts.append(project_number)
            
        filename_parts.extend([timestamp, f"{index:03d}"])
        
        return "_".join(filename_parts) + ext
    
    def process_single_image(self, image_path, output_path, watermark_path=None, settings=None):
        """Tek bir görseli işle"""
        try:
            # Varsayılan ayarlar
            if settings is None:
                settings = {
                    'max_width': 1000,
                    'max_height': 1000,
                    'watermark_position': 'bottom-right',
                    'watermark_opacity': 50
                }
            
            print(f"İşleniyor: {image_path}")
            
            # 1. Arka planı kaldır
            img = self.remove_background(image_path)
            
            # 2. Beyaz arka plan ekle
            img = self.add_white_background(img)
            
            # 3. Yeniden boyutlandır
            img = self.resize_image(
                img, 
                settings['max_width'], 
                settings['max_height']
            )
            
            # 4. Filigran ekle
            if watermark_path:
                img = self.add_watermark(
                    img, 
                    watermark_path,
                    settings['watermark_position'],
                    settings['watermark_opacity']
                )
            
            # 5. Kaydet
            img.save(output_path, 'JPEG', quality=95, optimize=True)
            
            self.processed_count += 1
            return True
            
        except Exception as e:
            print(f"Görsel işleme hatası: {e}")
            self.error_count += 1
            return False

# Flask route'ları
@app.route('/')
def index():
    """Ana sayfa"""
    return send_from_directory('.', 'index.html')

@app.route('/process', methods=['POST'])
def process_images():
    """Görselleri işle"""
    try:
        processor = PhotoProcessor()
        
        # Form verilerini al
        images = request.files.getlist('images')
        watermark = request.files.get('watermark')
        
        # Ayarları al
        settings = {
            'max_width': int(request.form.get('max_width', 1000)),
            'max_height': int(request.form.get('max_height', 1000)),
            'watermark_position': request.form.get('watermark_position', 'bottom-right'),
            'watermark_opacity': int(request.form.get('watermark_opacity', 50)),
            'brand_name': request.form.get('brand_name', '').upper(),
            'model_name': request.form.get('model_name', '').upper(),
            'project_number': request.form.get('project_number', '').upper()
        }
        
        # Filigranı kaydet
        watermark_path = None
        if watermark:
            watermark_filename = secure_filename(watermark.filename)
            watermark_path = os.path.join(WATERMARK_FOLDER, watermark_filename)
            watermark.save(watermark_path)
        
        # İşlenmiş dosyaların listesi
        processed_files = []
        
        # Her görseli işle
        for index, image in enumerate(images):
            if image:
                # Güvenli dosya adı
                filename = secure_filename(image.filename)
                
                # Geçici olarak kaydet
                temp_path = os.path.join(UPLOAD_FOLDER, filename)
                image.save(temp_path)
                
                # Yeni dosya adı oluştur
                new_filename = processor.generate_filename(
                    filename, 
                    index + 1,
                    settings['brand_name'],
                    settings['model_name'],
                    settings['project_number']
                )
                output_path = os.path.join(PROCESSED_FOLDER, new_filename)
                
                # Görseli işle
                success = processor.process_single_image(
                    temp_path,
                    output_path,
                    watermark_path,
                    settings
                )
                
                # Sonucu kaydet
                if success:
                    # Base64 olarak encode et (önizleme için)
                    with open(output_path, 'rb') as img_file:
                        img_data = base64.b64encode(img_file.read()).decode()
                    
                    processed_files.append({
                        'original': filename,
                        'filename': new_filename,
                        'status': 'success',
                        'url': f'data:image/jpeg;base64,{img_data}',
                        'path': output_path
                    })
                else:
                    processed_files.append({
                        'original': filename,
                        'filename': new_filename,
                        'status': 'error',
                        'url': '',
                        'path': ''
                    })
                
                # Geçici dosyayı sil
                os.remove(temp_path)
        
        # Sonuçları döndür
        return jsonify({
            'status': 'success',
            'total': len(images),
            'success': processor.processed_count,
            'error': processor.error_count,
            'processed_files': processed_files
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/download-all', methods=['GET'])
def download_all():
    """Tüm işlenmiş görselleri ZIP olarak indir"""
    try:
        # ZIP dosyası oluştur
        zip_path = os.path.join(STATIC_FOLDER, 'processed_images.zip')
        
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            # Processed klasöründeki tüm dosyaları ekle
            for filename in os.listdir(PROCESSED_FOLDER):
                file_path = os.path.join(PROCESSED_FOLDER, filename)
                if os.path.isfile(file_path):
                    zipf.write(file_path, filename)
        
        return send_file(zip_path, as_attachment=True, download_name='processed_images.zip')
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/clear', methods=['POST'])
def clear_folders():
    """Geçici dosyaları temizle"""
    try:
        # Klasörleri temizle
        for folder in [UPLOAD_FOLDER, PROCESSED_FOLDER, WATERMARK_FOLDER]:
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
        
        return jsonify({'status': 'success', 'message': 'Klasörler temizlendi'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("=" * 50)
    print("Fotoğraf İşleme Servisi Başlatılıyor...")
    print("=" * 50)
    print("Tarayıcınızda açın: http://localhost:8080")
    print("Durdurmak için: Ctrl+C")
    print("=" * 50)
    
    app.run(debug=True, host='127.0.0.1', port=8080)