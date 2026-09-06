from datetime import datetime, timedelta
import io
import os
import csv
from flask import Flask, redirect, render_template_string, request, url_for, Response, session
from flask_bcrypt import Bcrypt
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename
from google import genai

app = Flask(__name__)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'kunci-rahasia-sekolah-kita-yang-sangat-aman')
app.permanent_session_lifetime = timedelta(days=1)

db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///sekolah.db'

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

GEMINI_API_KEY = " "
ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

GOLONGAN_LKM_CONFIG = {
    '1': {'nama': 'Golongan 1: Primitive Knowing (Pengetahuan Awal)'},
    '2': {'nama': 'Golongan 2: Image Making (Pembentukan Gambaran)'},
    '3': {'nama': 'Golongan 3: Image Having (Memiliki Gambaran)'},
    '4': {'nama': 'Golongan 4: Property Noticing (Menyadari Sifat)'},
    '5': {'nama': 'Golongan 5: Formalising (Memformalkan)'},
    '6': {'nama': 'Golongan 6: Observing (Mengamati)'},
    '7': {'nama': 'Golongan 7: Structuring (Menyusun Struktur)'},
    '8': {'nama': 'Golongan 8: Inventising (Menciptakan)'},
}

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    nama = db.Column(db.String(150), nullable=True)

class PengaturanUjian(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama_ujian = db.Column(db.String(150), unique=True, nullable=False)
    status = db.Column(db.String(50), default='tutup')
    waktu_mulai = db.Column(db.String(50), nullable=True)
    waktu_selesai = db.Column(db.String(50), nullable=True)
    durasi_menit = db.Column(db.Integer, default=0)
    max_percobaan = db.Column(db.Integer, default=0)

class Pengumuman(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    judul = db.Column(db.String(200), nullable=False)
    isi = db.Column(db.Text, nullable=False)
    tanggal = db.Column(db.DateTime, default=datetime.utcnow)

class JawabanSiswa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama_siswa = db.Column(db.String(150), nullable=False)
    tugas = db.Column(db.String(150), nullable=False)
    kategori = db.Column(db.String(50), default='lkm')
    jawaban = db.Column(db.Text, nullable=True)
    foto = db.Column(db.String(300), nullable=True)
    nilai_angka = db.Column(db.Float, nullable=True, default=None)
    evaluasi_ai = db.Column(db.Text, nullable=True, default='Belum Dinilai / Belum Dianalisis AI')
    jumlah_kecurangan = db.Column(db.Integer, default=0)
    durasi_kecurangan_str = db.Column(db.String(100), default='0 detik')

class PertemuanLKM(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama_pertemuan = db.Column(db.String(200), nullable=False)

class SoalLKM(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pertemuan_id = db.Column(db.Integer, db.ForeignKey('pertemuan_lkm.id', ondelete='CASCADE'), nullable=False)
    golongan = db.Column(db.String(10), default='1')
    pertanyaan = db.Column(db.Text, nullable=False)
    kunci_jawaban = db.Column(db.Text, nullable=False)
    foto = db.Column(db.String(300), nullable=True)

class SoalLain(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    kategori = db.Column(db.String(50), nullable=False)
    pertanyaan = db.Column(db.Text, nullable=False)
    kunci_jawaban = db.Column(db.Text, nullable=False)
    foto = db.Column(db.String(300), nullable=True)

@login_manager.user_loader
def load_user(user_id):
    return db.get_or_404(User, int(user_id))

with app.app_context():
    db.create_all()
    try:
        with db.engine.connect() as conn:
            conn.execute(text('ALTER TABLE jawaban_siswa ADD COLUMN nilai_angka FLOAT'))
            conn.execute(text('ALTER TABLE jawaban_siswa ADD COLUMN evaluasi_ai TEXT'))
            conn.commit()
    except Exception:
        pass

    if not PengaturanUjian.query.filter_by(nama_ujian='Ujian Evaluasi').first():
        default_ujian = PengaturanUjian(nama_ujian='Ujian Evaluasi', status='buka_selalu', durasi_menit=0, max_percobaan=0)
        db.session.add(default_ujian)
        db.session.commit()

BASE_STYLE = """
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
    :root { 
        --bg-main: #f8fafc; 
        --card-bg: #ffffff; 
        --text-main: #0f172a; 
        --text-muted: #64748b; 
        --primary: #4f46e5; 
        --primary-hover: #4338ca; 
        --success: #10b981;
        --warning: #f59e0b;
        --danger: #f43f5e;
        --border-color: #e2e8f0; 
        --radius: 16px; 
        --shadow: 0 10px 25px -5px rgba(79, 70, 229, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.02); 
    }
    [data-theme="dark"] { 
        --bg-main: #0f172a; 
        --card-bg: #1e293b; 
        --text-main: #f8fafc; 
        --text-muted: #94a3b8; 
        --border-color: #334155; 
        --shadow: 0 20px 40px rgba(0, 0, 0, 0.4); 
    }
    * { box-sizing: border-box; }
    body { font-family: 'Plus Jakarta Sans', sans-serif; background: var(--bg-main); color: var(--text-main); margin: 0; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: flex-start; padding: 20px; transition: background 0.3s ease, color 0.3s ease; }
    
    .top-navbar { width: 100%; max-width: 1000px; background: var(--card-bg); border: 1px solid var(--border-color); padding: 12px 24px; border-radius: var(--radius); display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px; box-shadow: var(--shadow); }
    .nav-brand { font-weight: 800; font-size: 1.1rem; color: var(--text-main); display: flex; align-items: center; gap: 8px; text-decoration: none; }
    .nav-links { display: flex; gap: 12px; align-items: center; }

    .box, .container { background: var(--card-bg); border: 1px solid var(--border-color); padding: 40px; border-radius: var(--radius); box-shadow: var(--shadow); width: 100%; max-width: 1000px; animation: fadeInUp 0.4s cubic-bezier(0.16, 1, 0.3, 1); margin-bottom: 25px; transition: background 0.3s ease, border 0.3s ease; }
    @keyframes fadeInUp { from { opacity: 0; transform: translateY(15px); } to { opacity: 1; transform: translateY(0); } }
    
    h1, h2, h3 { color: var(--text-main); font-weight: 800; margin-top: 0; letter-spacing: -0.03em; }
    p, label { color: var(--text-muted); line-height: 1.6; font-weight: 500; }
    label { font-size: 0.9rem; color: var(--text-main); }
    a { color: var(--primary); text-decoration: none; font-weight: 700; transition: color 0.2s; }
    a:hover { color: var(--primary-hover); }
    
    .btn { background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%); color: white; padding: 14px 24px; border: none; border-radius: 12px; font-weight: 700; cursor: pointer; transition: all 0.25s ease; display: inline-flex; align-items: center; justify-content: center; gap: 8px; box-shadow: 0 8px 20px rgba(99, 102, 241, 0.25); text-decoration: none; width: 100%; }
    .btn:hover { transform: translateY(-2px); box-shadow: 0 12px 25px rgba(99, 102, 241, 0.35); filter: brightness(1.05); }
    .btn-success { background: linear-gradient(135deg, #34d399 0%, #059669 100%); box-shadow: 0 8px 20px rgba(5, 150, 105, 0.25); }
    .btn-danger { background: linear-gradient(135deg, #f43f5e 0%, #e11d48 100%); box-shadow: 0 8px 20px rgba(244, 63, 94, 0.25); }
    .btn-warning { background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); box-shadow: 0 8px 20px rgba(245, 158, 11, 0.25); }
    .btn-secondary { background: var(--border-color); color: var(--text-main); box-shadow: none; }
    .btn-secondary:hover { background: var(--text-muted); color: white; }

    input[type="text"], input[type="password"], input[type="number"], input[type="datetime-local"], textarea, select { width: 100%; padding: 14px 16px; margin-top: 6px; margin-bottom: 20px; background: var(--bg-main); border: 2px solid var(--border-color); border-radius: 12px; color: var(--text-main); font-family: inherit; font-size: 0.95rem; font-weight: 500; transition: all 0.2s ease; }
    input:focus, textarea:focus, select:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.15); }
    
    .theme-toggle { background: transparent; border: 2px solid var(--border-color); color: var(--text-main); padding: 8px 14px; border-radius: 10px; cursor: pointer; font-weight: 700; font-size: 0.85rem; transition: all 0.2s; display: inline-flex; align-items: center; gap: 6px; }
    .theme-toggle:hover { border-color: var(--primary); color: var(--primary); }
    
    .table-container { width: 100%; overflow-x: auto; margin-top: 15px; border-radius: 12px; border: 1px solid var(--border-color); background: var(--card-bg); }
    table { width: 100%; border-collapse: collapse; min-width: 600px; }
    th, td { padding: 16px; text-align: left; border-bottom: 1px solid var(--border-color); }
    th { background: var(--bg-main); color: var(--text-main); font-weight: 700; border-right: none; }
    td { border-right: none; }
    tbody tr:hover { background: var(--bg-main); }

    .empty-state { text-align: center; padding: 45px 20px; background: var(--bg-main); border: 2px dashed var(--border-color); border-radius: 14px; margin: 20px 0; }
    .empty-state-icon { font-size: 3rem; margin-bottom: 10px; }
    .empty-state-text { color: var(--text-muted); font-weight: 600; font-size: 0.95rem; margin-bottom: 15px; }

    #loading-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(15, 23, 42, 0.6); backdrop-filter: blur(4px); z-index: 99999; display: none; flex-direction: column; align-items: center; justify-content: center; color: white; font-weight: 700; }
    .spinner { width: 50px; height: 50px; border: 5px solid rgba(255,255,255,0.3); border-radius: 50%; border-top-color: white; animation: spin 0.8s linear infinite; margin-bottom: 15px; }
    @keyframes spin { to { transform: rotate(360deg); } }

    .calc-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(50px, 1fr)); gap: 6px; margin-top: 8px; }
    .calc-btn { background: var(--bg-main); border: 2px solid var(--border-color); color: var(--text-main); padding: 10px; border-radius: 8px; font-weight: 700; cursor: pointer; text-align: center; font-size: 0.95rem; }
    .calc-btn:hover { border-color: var(--primary); color: var(--primary); background: rgba(99, 102, 241, 0.05); }
    
    #toast-container { position: fixed; bottom: 25px; right: 25px; z-index: 9999; display: flex; flex-direction: column; gap: 10px; }
    .toast { background: #10b981; color: white; padding: 14px 22px; border-radius: 12px; font-weight: 700; box-shadow: 0 10px 25px rgba(0,0,0,0.15); animation: slideIn 0.3s ease, fadeOut 0.3s ease 2.7s forwards; display: flex; align-items: center; gap: 10px; }
    .toast.error { background: #ef4444; }
    @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
    @keyframes fadeOut { to { opacity: 0; transform: translateY(10px); } }
</style>
<script>
    function toggleTheme() {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('theme', newTheme);
    }
    document.addEventListener('DOMContentLoaded', () => {
        const savedTheme = localStorage.getItem('theme') || 'light';
        document.documentElement.setAttribute('data-theme', savedTheme);
    });
    function showToast(message, isError = false) {
        let container = document.getElementById('toast-container');
        if(!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            document.body.appendChild(container);
        }
        const toast = document.createElement('div');
        toast.className = 'toast' + (isError ? ' error' : '');
        toast.innerHTML = (isError ? '&#9888; ' : '&#10004; ') + message;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }
    function showLoading(text = "Memproses...") {
        let overlay = document.getElementById('loading-overlay');
        if(!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'loading-overlay';
            overlay.innerHTML = '<div class="spinner"></div><div id="loading-text">Memproses...</div>';
            document.body.appendChild(overlay);
        }
        document.getElementById('loading-text').innerText = text;
        overlay.style.display = 'flex';
    }
    function switchTab(tabId) {
        document.getElementById('section-akun').style.display = (tabId === 'akun' ? 'block' : 'none');
        document.getElementById('section-ujian').style.display = (tabId === 'ujian' ? 'block' : 'none');
        document.getElementById('tab-btn-akun').style.background = (tabId === 'akun' ? 'var(--primary)' : 'var(--card-bg)');
        document.getElementById('tab-btn-akun').style.color = (tabId === 'akun' ? 'white' : 'var(--text-main)');
        document.getElementById('tab-btn-ujian').style.background = (tabId === 'ujian' ? 'var(--primary)' : 'var(--card-bg)');
        document.getElementById('tab-btn-ujian').style.color = (tabId === 'ujian' ? 'white' : 'var(--text-main)');
    }
</script>
"""

def render_navbar():
    if not current_user.is_authenticated:
        return ""
    dash_url = '/dashboard/siswa' if current_user.role == 'siswa' else '/dashboard/guru'
    role_label = "Siswa" if current_user.role == 'siswa' else "Guru Pengampu"
    return f"""
    <div class="top-navbar">
        <a href="{dash_url}" class="nav-brand">Portal Sekolah ({role_label})</a>
        <div class="nav-links">
            <a href="/profil" class="theme-toggle" style="text-decoration:none;">Profil</a>
            <button class="theme-toggle" onclick="toggleTheme()">Tema</button>
            <a href="/logout" class="btn btn-danger" style="padding: 8px 16px; width:auto; font-size:0.85rem; box-shadow:none;">Logout</a>
        </div>
    </div>
    """

@app.errorhandler(404)
def page_not_found(e):
    return '<!DOCTYPE html><html lang="id"><head><title>404 Tidak Ditemukan</title>' + BASE_STYLE + '</head><body><div class="box" style="text-align:center; max-width:450px; margin-top:80px;"><div style="font-size:3.5rem; margin-bottom:10px;">🔍</div><h2>404 - Halaman Tidak Ditemukan</h2><p>Maaf, halaman atau tautan yang Anda tuju tidak tersedia.</p><a href="/" class="btn" style="margin-top:15px;">Kembali ke Beranda</a></div></body></html>', 404

@app.errorhandler(500)
def internal_server_error(e):
    return '<!DOCTYPE html><html lang="id"><head><title>500 Kesalahan Server</title>' + BASE_STYLE + '</head><body><div class="box" style="text-align:center; max-width:450px; margin-top:80px;"><div style="font-size:3.5rem; margin-bottom:10px;">&#9888;</div><h2>500 - Terjadi Kesalahan</h2><p>Maaf, sistem mengalami gangguan internal. Silakan coba beberapa saat lagi.</p><a href="/" class="btn" style="margin-top:15px;">Kembali ke Beranda</a></div></body></html>', 500

@app.route('/')
def beranda():
    return '<!DOCTYPE html><html lang="id"><head><title>Portal Sekolah</title>' + BASE_STYLE + """</head><body><div id="toast-container"></div><div class="box" style="text-align: center; max-width: 450px;"><div style="display:flex; justify-content:flex-end; margin-bottom:15px;"><button class="theme-toggle" onclick="toggleTheme()">Tema</button></div><h1>Portal Akademik Sekolah</h1><p style="margin-bottom: 30px;">Silakan masuk untuk melanjutkan.</p><div style="display: flex; gap: 12px; flex-direction: column;"><a href="/login" class="btn">Masuk (Login)</a><a href="/register" class="btn btn-secondary">Daftar Akun Baru</a></div></div></body></html>"""

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nama = request.form.get('nama', '').strip()
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(username=username, password=hashed_password, role=role, nama=nama)
        try:
            db.session.add(new_user)
            db.session.commit()
            return redirect(url_for('login'))
        except IntegrityError:
            db.session.rollback()
            return '<script>alert("Username sudah digunakan! Silakan pilih username lain.");window.location="/register";</script>'
    return '<!DOCTYPE html><html lang="id"><head><title>Daftar</title>' + BASE_STYLE + """</head><body><div id="toast-container"></div><div class="box" style="max-width: 420px;"><div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;"><h2>Daftar Akun</h2><button class="theme-toggle" onclick="toggleTheme()">Tema</button></div><form method="POST" onsubmit="showLoading('Mendaftarkan akun...')"><label>Nama Lengkap:</label><input type="text" name="nama" required><label>Username:</label><input type="text" name="username" required><label>Password:</label><input type="password" name="password" required><label>Sebagai:</label><select name="role"><option value="siswa">Siswa</option><option value="guru">Guru</option></select><button type="submit" class="btn" style="margin-top:10px;">Daftar</button></form><center><a href="/" style="display:inline-block; margin-top:20px; font-size:0.9rem;">&larr; Kembali ke Beranda</a></center></div></body></html>"""

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            session.permanent = True
            if user.role == 'siswa':
                return redirect(url_for('dashboard_siswa'))
            else:
                return redirect(url_for('dashboard_guru'))
        else:
            return '<script>alert("Login Gagal! Periksa username dan password.");window.location="/login";</script>'
    return '<!DOCTYPE html><html lang="id"><head><title>Login</title>' + BASE_STYLE + """</head><body><div id="toast-container"></div><div class="box" style="max-width: 420px;"><div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;"><h2>Login Sistem</h2><button class="theme-toggle" onclick="toggleTheme()">Tema</button></div><form method="POST" onsubmit="showLoading('Memproses masuk...')"><label>Username:</label><input type="text" name="username" required><label>Password:</label><input type="password" name="password" required><button type="submit" class="btn" style="margin-top:10px;">Masuk</button></form><center><a href="/" style="display:inline-block; margin-top:20px; font-size:0.9rem;">&larr; Kembali ke Beranda</a></center></div></body></html>"""

@app.route('/profil', methods=['GET', 'POST'])
@login_required
def profil():
    error, success = None, None
    if request.method == 'POST':
        new_nama = request.form.get('nama', '').strip()
        new_username = request.form.get('username', '').strip()
        new_password = request.form.get('password', '').strip()
        
        if new_nama:
            current_user.nama = new_nama
        if new_username and new_username != current_user.username:
            existing = User.query.filter_by(username=new_username).first()
            if existing:
                error = 'Username sudah digunakan oleh akun lain!'
            else:
                current_user.username = new_username
        if new_password and not error:
            current_user.password = bcrypt.generate_password_hash(new_password).decode('utf-8')
            
        if not error:
            db.session.commit()
            success = 'Profil berhasil diperbarui!'
            
    return '<!DOCTYPE html><html lang="id"><head><title>Manajemen Profil</title>' + BASE_STYLE + """</head><body><div id="toast-container"></div>{navbar}<div class="box" style="max-width: 500px;"><h2 style="margin-bottom:20px;">&#9881;&#65039; Pengaturan Profil</h2>{error_div}{success_div}<form method="POST" onsubmit="showLoading('Menyimpan profil...')"><label>Nama Lengkap:</label><input type="text" name="nama" value="{nama_val}" required><label>Username:</label><input type="text" name="username" value="{user_val}" required><label>Password Baru (Kosongkan jika tidak diubah):</label><input type="password" name="password" placeholder="Masukkan password baru..."><button type="submit" class="btn" style="margin-top:10px;">Simpan Perubahan</button></form></div></body></html>""".replace('{navbar}', render_navbar()).replace('{error_div}', f'<div style="background: #fef2f2; border: 2px solid #fecaca; color: #dc2626; padding: 12px; border-radius: 12px; margin-bottom: 20px;">{error}</div>' if error else '').replace('{success_div}', f'<div style="background: #ecfdf5; border: 2px solid #a7f3d0; color: #065f46; padding: 12px; border-radius: 12px; margin-bottom: 20px;">{success}</div><script>showToast("Profil berhasil diperbarui!");</script>' if success else '').replace('{nama_val}', current_user.nama or '').replace('{user_val}', current_user.username)

@app.route('/dashboard/siswa')
@login_required
def dashboard_siswa():
    if current_user.role != 'siswa':
        return 'Akses ditolak!'
    display_name = current_user.nama or current_user.username
    
    semua_pengumuman = Pengumuman.query.order_by(Pengumuman.tanggal.desc()).all()
    pengumuman_html = ''
    for peng in semua_pengumuman:
        pengumuman_html += f"""
        <div style="background: var(--bg-main); border-left: 4px solid var(--primary); padding: 16px; border-radius: 0 12px 12px 0; margin-bottom: 12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 6px;">
                <strong style="font-size: 1rem; color: var(--text-main);">{peng.judul}</strong>
                <span style="font-size: 0.75rem; color: var(--text-muted);">{peng.tanggal.strftime('%d %b %Y, %H:%M')}</span>
            </div>
            <p style="margin: 0; font-size: 0.9rem; white-space: pre-line;">{peng.isi}</p>
        </div>
        """

    if not pengumuman_html:
        pengumuman_html = '<div class="empty-state"><div class="empty-state-icon">&#128237;</div><div class="empty-state-text">Belum ada pengumuman dari guru saat ini.</div></div>'

    return '<!DOCTYPE html><html lang="id"><head><title>Dasbor Siswa</title>' + BASE_STYLE + """</head><body><div id="toast-container"></div>{navbar}<div class="box"><h2 style="margin-bottom:20px;">Halo, Siswa {username}! &#128075;</h2>
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 20px; margin-bottom: 35px;">
        <a href="/siswa/pilih-ujian" class="box" style="margin:0; text-decoration:none; display:block; border: 2px solid var(--border-color);"><h3>&#128221; Kerjakan Ujian / Tugas</h3><p style="margin:8px 0 0 0; font-size:0.85rem;">Akses modul LKM, Latihan, & Evaluasi.</p></a>
        <a href="/siswa/riwayat" class="box" style="margin:0; text-decoration:none; display:block; border: 2px solid var(--border-color);"><h3>&#128202; Riwayat & Nilai</h3><p style="margin:8px 0 0 0; font-size:0.85rem;">Cek transkrip nilai dan ulasan AI.</p></a>
    </div>
    <div>
        <h3 style="margin-bottom: 15px; border-bottom: 2px solid var(--border-color); padding-bottom: 8px;">Papan Pengumuman Guru</h3>
        {pengumuman_list}
    </div>
</div></body></html>""".replace('{navbar}', render_navbar()).replace('{username}', display_name).replace('{pengumuman_list}', pengumuman_html)

@app.route('/dashboard/guru', methods=['GET', 'POST'])
@login_required
def dashboard_guru():
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    if request.method == 'POST':
        judul = request.form.get('judul')
        isi = request.form.get('isi')
        if judul and isi:
            new_p = Pengumuman(judul=judul, isi=isi)
            db.session.add(new_p)
            db.session.commit()
            return redirect(url_for('dashboard_guru'))
            
    semua_pengumuman = Pengumuman.query.order_by(Pengumuman.tanggal.desc()).all()
    pengumuman_guru_html = ''
    for peng in semua_pengumuman:
        pengumuman_guru_html += f"""
        <div style="background: var(--bg-main); border: 2px solid var(--border-color); padding: 16px; border-radius: 12px; margin-bottom: 12px; display:flex; justify-content:space-between; align-items:flex-start;">
            <div>
                <strong style="font-size: 1rem; color: var(--text-main);">{peng.judul}</strong>
                <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 6px;">{peng.tanggal.strftime('%d %b %Y, %H:%M')}</div>
                <p style="margin: 0; font-size: 0.9rem; white-space: pre-line;">{peng.isi}</p>
            </div>
            <a href="/guru/hapus-pengumuman/{peng.id}" class="btn btn-danger" style="padding: 6px 10px; font-size: 0.75rem; width: auto;" onclick="return confirm('Hapus pengumuman ini?')">Hapus</a>
        </div>
        """

    if not pengumuman_guru_html:
        pengumuman_guru_html = '<div class="empty-state"><div class="empty-state-icon">&#128226;</div><div class="empty-state-text">Belum ada pengumuman yang dipublikasikan.</div></div>'

    return '<!DOCTYPE html><html lang="id"><head><title>Dasbor Guru</title>' + BASE_STYLE + """</head><body><div id="toast-container"></div>{navbar}<div class="box"><h2 style="margin-bottom:20px;">Panel Pengontrol Guru</h2>
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-top: 15px; margin-bottom: 35px;">
        <a href="/guru/bank-soal" class="box" style="margin:0; text-decoration:none; display:block; border: 2px solid var(--border-color);"><h3>&#128193; Bank Soal</h3></a>
        <a href="/guru/koreksi" class="box" style="margin:0; text-decoration:none; display:block; border: 2px solid var(--border-color);"><h3>&#128221; Koreksi Jawaban</h3></a>
        <a href="/guru/laporan" class="box" style="margin:0; text-decoration:none; display:block; border: 2px solid var(--border-color);"><h3>&#128202; Analitik Kelas</h3></a>
        <a href="/guru/ekspor-excel" class="box" style="margin:0; text-decoration:none; display:block; border: 2px solid var(--border-color);"><h3>&#128229; Ekspor Rekap</h3></a>
        <a href="/guru/pengaturan-ujian" class="box" style="margin:0; text-decoration:none; display:block; border: 2px solid var(--border-color);"><h3>&#9881;&#65039; Pengaturan Waktu</h3></a>
        <a href="/guru/kelola-akun" class="box" style="margin:0; text-decoration:none; display:block; border: 2px solid var(--border-color); background:#fef2f2;"><h3>&#128101; Kelola Akun & Ujian</h3></a>
    </div>
    <div style="background: var(--card-bg); border: 2px solid var(--border-color); padding: 25px; border-radius: 16px;">
        <h3>&#128226; Buat Pengumuman Kelas</h3>
        <form method="POST" onsubmit="showLoading('Memublikasikan...')">
            <label>Judul Pengumuman:</label>
            <input type="text" name="judul" required placeholder="Contoh: Jadwal Ujian Susulan">
            <label>Isi Pesan:</label>
            <textarea name="isi" required placeholder="Tuliskan isi pengumuman..." style="height: 100px;"></textarea>
            <button type="submit" class="btn btn-success" style="width: auto;">Publikasikan Pengumuman</button>
        </form>
        <h3 style="margin-top: 30px; border-bottom: 2px solid var(--border-color); padding-bottom: 8px;">Daftar Pengumuman Aktif</h3>
        {pengumuman_guru_list}
    </div>
</div></body></html>""".replace('{navbar}', render_navbar()).replace('{pengumuman_guru_list}', pengumuman_guru_html)

@app.route('/guru/kelola-akun', methods=['GET', 'POST'])
@login_required
def kelola_akun():
    if current_user.role != 'guru': return 'Akses ditolak!'
    if request.method == 'POST':
        action = request.form.get('action')
        user_id = request.form.get('user_id')
        siswa = User.query.get(user_id)
        if siswa and siswa.role == 'siswa':
            if action == 'hapus':
                db.session.delete(siswa)
                db.session.commit()
                return '<script>alert("Akun siswa dihapus!");window.location="/guru/kelola-akun";</script>'
            elif action == 'reset':
                new_pass = request.form.get('new_password')
                siswa.password = bcrypt.generate_password_hash(new_pass).decode('utf-8')
                db.session.commit()
                return '<script>alert("Password berhasil direset!");window.location="/guru/kelola-akun";</script>'
            elif action == 'buka_akses':
                kategori_tugas = request.form.get('kategori_tugas')
                nama_identitas = siswa.nama or siswa.username
                if kategori_tugas.startswith('lkm_'):
                    pertemuan_id = kategori_tugas.split('_')[1]
                    p_obj = PertemuanLKM.query.get(pertemuan_id)
                    p_nama = f"LKM - {p_obj.nama_pertemuan}" if p_obj else ""
                    JawabanSiswa.query.filter_by(nama_siswa=nama_identitas, tugas=p_nama).delete()
                elif kategori_tugas == 'latihan':
                    JawabanSiswa.query.filter_by(nama_siswa=nama_identitas, kategori='latihan').delete()
                elif kategori_tugas == 'evaluasi':
                    JawabanSiswa.query.filter_by(nama_siswa=nama_identitas, kategori='evaluasi').delete()
                db.session.commit()
                return '<script>alert("Akses ujian/modul siswa berhasil dibuka kembali!");window.location="/guru/kelola-akun";</script>'

    daftar_siswa = User.query.filter_by(role='siswa').all()
    semua_pertemuan = PertemuanLKM.query.all()
    
    html_siswa_akun = ''
    for s in daftar_siswa:
        html_siswa_akun += f"""<tr>
            <td>{s.nama} ({s.username})</td>
            <td>
                <form method="POST" style="display:inline-flex; gap:8px; align-items:center; margin:0;">
                    <input type="hidden" name="action" value="reset">
                    <input type="hidden" name="user_id" value="{s.id}">
                    <input type="text" name="new_password" placeholder="Password Baru" required style="padding:8px; margin:0; width:150px;">
                    <button type="submit" class="btn btn-warning" style="padding:8px 14px; width:auto; font-size:0.85rem;">Reset</button>
                </form>
            </td>
            <td>
                <form method="POST" style="display:inline-block; margin:0;" onsubmit="return confirm('Hapus akun {s.nama}?');">
                    <input type="hidden" name="action" value="hapus">
                    <input type="hidden" name="user_id" value="{s.id}">
                    <button type="submit" class="btn btn-danger" style="padding:8px 14px; width:auto; font-size:0.85rem;">Hapus Akun</button>
                </form>
            </td>
        </tr>"""
    if not html_siswa_akun: html_siswa_akun = '<tr><td colspan="3">Belum ada akun siswa terdaftar.</td></tr>'

    html_siswa_ujian = ''
    for s in daftar_siswa:
        nama_identitas = s.nama or s.username
        rincian_status_html = ""
        
        for p in semua_pertemuan:
            t_lkm = JawabanSiswa.query.filter_by(nama_siswa=nama_identitas, tugas=f"LKM - {p.nama_pertemuan}").first()
            status_str = "Belum dikerjakan"
            if t_lkm:
                status_str = f"Terkirim (Nilai: {t_lkm.nilai_angka if t_lkm.nilai_angka is not None else 'Belum Dinilai'})"
            
            rincian_status_html += f"""
            <div style="background:var(--bg-main); border:1px solid var(--border-color); padding:10px; border-radius:10px; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <strong style="font-size:0.9rem;">&#128218; LKM - {p.nama_pertemuan}</strong><br>
                    <span style="font-size:0.8rem; color:var(--text-muted);">Status: {status_str}</span>
                </div>
                <form method="POST" style="margin:0;">
                    <input type="hidden" name="action" value="buka_akses">
                    <input type="hidden" name="user_id" value="{s.id}">
                    <input type="hidden" name="kategori_tugas" value="lkm_{p.id}">
                    <button type="submit" class="btn" style="padding:6px 12px; font-size:0.75rem; width:auto; background:linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);">Buka Akses</button>
                </form>
            </div>
            """
            
        t_lat = JawabanSiswa.query.filter_by(nama_siswa=nama_identitas, kategori='latihan').first()
        status_lat = "Belum dikerjakan" if not t_lat else f"Terkirim (Nilai: {t_lat.nilai_angka if t_lat.nilai_angka is not None else 'Belum Dinilai'})"
        rincian_status_html += f"""
        <div style="background:var(--bg-main); border:1px solid var(--border-color); padding:10px; border-radius:10px; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
            <div>
                <strong style="font-size:0.9rem;">&#128221; Soal Latihan Mandiri</strong><br>
                <span style="font-size:0.8rem; color:var(--text-muted);">Status: {status_lat}</span>
            </div>
            <form method="POST" style="margin:0;">
                <input type="hidden" name="action" value="buka_akses">
                <input type="hidden" name="user_id" value="{s.id}">
                <input type="hidden" name="kategori_tugas" value="latihan">
                <button type="submit" class="btn" style="padding:6px 12px; font-size:0.75rem; width:auto; background:linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);">Buka Akses</button>
            </form>
        </div>
        """

        t_ev = JawabanSiswa.query.filter_by(nama_siswa=nama_identitas, kategori='evaluasi').first()
        status_ev = "Belum dikerjakan" if not t_ev else f"Terkirim (Nilai: {t_ev.nilai_angka if t_ev.nilai_angka is not None else 'Belum Dinilai'})"
        rincian_status_html += f"""
        <div style="background:var(--bg-main); border:1px solid var(--border-color); padding:10px; border-radius:10px; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
            <div>
                <strong style="font-size:0.9rem;">&#9888; Ujian Evaluasi Resmi</strong><br>
                <span style="font-size:0.8rem; color:var(--text-muted);">Status: {status_ev}</span>
            </div>
            <form method="POST" style="margin:0;">
                <input type="hidden" name="action" value="buka_akses">
                <input type="hidden" name="user_id" value="{s.id}">
                <input type="hidden" name="kategori_tugas" value="evaluasi">
                <button type="submit" class="btn btn-danger" style="padding:6px 12px; font-size:0.75rem; width:auto;">Buka Akses</button>
            </form>
        </div>
        """

        html_siswa_ujian += f"""<tr>
            <td style="vertical-align:top; font-weight:700;">{s.nama}<br><span style="font-size:0.8rem; color:var(--text-muted);">({s.username})</span></td>
            <td>{rincian_status_html}</td>
        </tr>"""
        
    if not html_siswa_ujian: html_siswa_ujian = '<tr><td colspan="2">Belum ada akun siswa terdaftar.</td></tr>'

    return '<!DOCTYPE html><html lang="id"><head><title>Kelola Akun & Ujian</title>' + BASE_STYLE + f"""</head><body>{render_navbar()}<div id="toast-container"></div><div class="box" style="max-width: 1050px;"><h2>&#128101; Manajemen Akun & Buka Akses Ujian Siswa</h2><p style="font-size:0.9rem; color:var(--text-muted); margin-bottom:20px;">Kelola kredensial akun siswa atau buka kembali akses pengerjaan ujian/tugas secara spesifik.</p>

<div style="display:flex; gap:12px; margin-bottom:25px; border-bottom:2px solid var(--border-color); padding-bottom:15px;">
    <button type="button" id="tab-btn-akun" class="btn" onclick="switchTab('akun')" style="width:auto; background:var(--primary); color:white;">&#128100; Tab 1: Akun Siswa (Reset & Hapus)</button>
    <button type="button" id="tab-btn-ujian" class="btn btn-secondary" onclick="switchTab('ujian')" style="width:auto;">&#128221; Tab 2: Buka Akses Ujian Per Pertemuan</button>
</div>

<div id="section-akun">
    <h3 style="margin-bottom:15px;">Daftar Akun Siswa & Keamanan</h3>
    <div class="table-container">
        <table>
            <tr><th>Nama & Username</th><th>Reset Password</th><th>Aksi Hapus</th></tr>
            {html_siswa_akun}
        </table>
    </div>
</div>

<div id="section-ujian" style="display:none;">
    <h3 style="margin-bottom:15px;">Rincian Status & Pembukaan Akses Ujian Siswa</h3>
    <p style="font-size:0.85rem; color:var(--text-muted); margin-bottom:15px;">Klik tombol "Buka Akses" pada modul atau pertemuan tertentu untuk mereset jawaban siswa.</p>
    <div class="table-container">
        <table>
            <tr><th style="width:250px;">Siswa</th><th>Rincian Modul / LKM Pertemuan & Tombol Buka Akses</th></tr>
            {html_siswa_ujian}
        </table>
    </div>
</div>

</div></body></html>"""

@app.route('/guru/hapus-pengumuman/<int:id_p>')
@login_required
def hapus_pengumuman(id_p):
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    peng = db.get_or_404(Pengumuman, id_p)
    db.session.delete(peng)
    db.session.commit()
    return redirect(url_for('dashboard_guru'))

@app.route('/siswa/pilih-ujian')
@login_required
def pilih_ujian():
    if current_user.role != 'siswa':
        return 'Akses ditolak!'
    
    user_name = current_user.nama or current_user.username
    daftar_pertemuan = PertemuanLKM.query.all()
    lkm_html_list = ''
    semua_lkm_lulus = True if daftar_pertemuan else False
    
    for p in daftar_pertemuan:
        tugas_p = JawabanSiswa.query.filter_by(nama_siswa=user_name, tugas=f"LKM - {p.nama_pertemuan}").first()
        status_teks = "Belum dikerjakan"
        sudah_lulus_p = False
        sudah_kumpul = False
        
        if tugas_p:
            sudah_kumpul = True
            if tugas_p.nilai_angka is not None:
                if tugas_p.nilai_angka >= 75:
                    sudah_lulus_p = True
                    status_teks = f"Lulus (Nilai: {tugas_p.nilai_angka}) - Telah Dikumpulkan"
                else:
                    sudah_lulus_p = False
                    semua_lkm_lulus = False
                    status_teks = f"Belum Lulus (Nilai: {tugas_p.nilai_angka}, Min: 75) - Telah Dikumpulkan"
            else:
                semua_lkm_lulus = False
                status_teks = "Menunggu penilaian guru - Telah Dikumpulkan"
        else:
            semua_lkm_lulus = False
            
        if sudah_kumpul:
            btn_html = '<span style="color:var(--text-muted); font-size:0.85rem; font-weight:700; background:var(--border-color); padding:8px 14px; border-radius:8px;">Sudah Dikumpulkan &#128274;</span>'
        else:
            btn_html = f'<a href="/siswa/kerjakan/lkm/{p.id}" class="btn" style="width:auto; padding:10px 20px;">Kerjakan</a>'

        lkm_html_list += f"""
        <div style="background:var(--bg-main); border:2px solid var(--border-color); padding:20px; border-radius:14px; display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <div>
                <h3 style="margin:0 0 4px 0;">&#128218; {p.nama_pertemuan}</h3>
                <p style="margin:0; font-size:0.85rem;">Status: <b>{status_teks}</b></p>
            </div>
            {btn_html}
        </div>
        """
        
    if not lkm_html_list:
        lkm_html_list = '<div class="empty-state"><div class="empty-state-icon">&#128218;</div><div class="empty-state-text">Belum ada modul LKM yang tersedia dari guru.</div></div>'
        semua_lkm_lulus = False

    t_lat_cek = JawabanSiswa.query.filter_by(nama_siswa=user_name, kategori='latihan').first()
    t_ev_cek = JawabanSiswa.query.filter_by(nama_siswa=user_name, kategori='evaluasi').first()

    if semua_lkm_lulus:
        if not t_lat_cek:
            tombol_latihan = '<a href="/siswa/kerjakan/latihan" class="btn" style="background:linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);"><h3>Soal Latihan</h3><p style="font-size: 13px; margin: 0; color:white;">Latihan Mandiri</p></a>'
        else:
            tombol_latihan = '<div style="flex: 1; padding: 20px; background: var(--bg-main); border: 2px solid var(--border-color); color: var(--text-muted); border-radius: 12px; text-align:center;"><h3>Soal Latihan &#128274;</h3><p style="font-size: 13px; margin: 0;">Sudah Dikumpulkan</p></div>'

        if not t_ev_cek:
            tombol_evaluasi = '<a href="/siswa/kerjakan/evaluasi" class="btn btn-danger"><h3>Soal Evaluasi</h3><p style="font-size: 13px; margin: 0; color:white;">Ujian Resmi</p></a>'
        else:
            tombol_evaluasi = '<div style="flex: 1; padding: 20px; background: var(--bg-main); border: 2px solid var(--border-color); color: var(--text-muted); border-radius: 12px; text-align:center;"><h3>Soal Evaluasi &#128274;</h3><p style="font-size: 13px; margin: 0;">Sudah Dikumpulkan</p></div>'
    else:
        tombol_latihan = '<div style="flex: 1; padding: 20px; background: var(--bg-main); border: 2px dashed var(--border-color); color: var(--text-muted); border-radius: 12px; text-align:center; cursor:pointer;" onclick="showToast(\'Akses terkunci! Selesaikan semua pertemuan LKM dengan nilai minimal 75.\', true)"><h3>Soal Latihan &#128274;</h3><p style="font-size: 13px; margin: 0;">Terkunci (LKM belum tuntas semua)</p></div>'
        tombol_evaluasi = '<div style="flex: 1; padding: 20px; background: var(--bg-main); border: 2px dashed var(--border-color); color: var(--text-muted); border-radius: 12px; text-align:center; cursor:pointer;" onclick="showToast(\'Akses terkunci! Selesaikan semua pertemuan LKM dengan nilai minimal 75.\', true)"><h3>Soal Evaluasi &#128274;</h3><p style="font-size: 13px; margin: 0;">Terkunci (LKM belum tuntas semua)</p></div>'

    return '<!DOCTYPE html><html lang="id"><head><title>Pilih Modul</title>' + BASE_STYLE + """</head><body><div id="toast-container"></div>{navbar}<div class="box" style="max-width: 900px; text-align: center;"><h1>&#128221; Pilih Modul Tugas / Ujian</h1><p>Kerjakan lembar kerja murid (LKM) per pertemuan terlebih dahulu. Selesaikan seluruhnya minimal nilai 75 untuk membuka Soal Latihan & Evaluasi.</p><hr style="margin: 20px 0; border:0; border-top:1px solid var(--border-color);"><div style="text-align:left; margin-bottom:30px;"><h3 style="margin-bottom:15px;">Daftar Pertemuan LKM:</h3>{lkm_html_list}</div><hr style="margin: 20px 0; border:0; border-top:1px solid var(--border-color);"><h3 style="margin-bottom:15px; text-align:left;">Ujian Lanjutan (Terkunci jika LKM belum tuntas):</h3><div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px;">{tombol_latihan}{tombol_evaluasi}</div></div></body></html>""".replace('{navbar}', render_navbar()).replace('{lkm_html_list}', lkm_html_list).replace('{tombol_latihan}', tombol_latihan).replace('{tombol_evaluasi}', tombol_evaluasi)

@app.route('/guru/bank-soal')
@login_required
def bank_soal():
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    return '<!DOCTYPE html><html lang="id"><head><title>Bank Soal</title>' + BASE_STYLE + """</head><body><div id="toast-container"></div>{navbar}<div class="box" style="max-width: 650px;"><h2 style="margin-bottom:5px;">&#128193; Bank Soal Guru</h2><p>Pilih kategori modul soal untuk dikelola:</p><div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 15px; margin-top: 20px;"><a href="/guru/bank-soal/lkm" class="btn btn-success"><h3>LKM</h3></a><a href="/guru/bank-soal/latihan" class="btn" style="background:linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);"><h3>Soal Latihan</h3></a><a href="/guru/bank-soal/evaluasi" class="btn btn-danger"><h3>Soal Evaluasi</h3></a></div></div></body></html>""".replace('{navbar}', render_navbar())

@app.route('/guru/bank-soal/lkm', methods=['GET', 'POST'])
@login_required
def guru_pertemuan_lkm():
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    if request.method == 'POST':
        nama_p = request.form.get('nama_pertemuan')
        if nama_p:
            new_p = PertemuanLKM(nama_pertemuan=nama_p)
            db.session.add(new_p)
            db.session.commit()
            return redirect(url_for('guru_pertemuan_lkm'))
    daftar_pertemuan = PertemuanLKM.query.all()
    html_list = ''
    for p in daftar_pertemuan:
        jumlah_soal = SoalLKM.query.filter_by(pertemuan_id=p.id).count()
        html_list += f"""
        <div style="background: var(--bg-main); border: 2px solid var(--border-color); padding: 20px; border-radius: 12px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;">
            <div>
                <a href="/guru/bank-soal/lkm/detail/{p.id}" style="font-size: 1.1rem; font-weight: 700;">&#128197; {p.nama_pertemuan}</a>
                <div style="font-size: 0.85rem; color: var(--text-muted); margin-top: 4px;">Jumlah Soal: {jumlah_soal} Soal</div>
            </div>
            <a href="/guru/bank-soal/lkm/hapus-pertemuan/{p.id}" class="btn btn-danger" style="padding: 8px 14px; font-size: 0.8rem; width: auto;" onclick="return confirm('Hapus pertemuan ini beserta seluruh soal di dalamnya?')">Hapus</a>
        </div>
        """
    if not html_list:
        html_list = '<div class="empty-state"><div class="empty-state-icon">&#128197;</div><div class="empty-state-text">Belum ada pertemuan LKM yang dibuat.</div></div>'

    return '<!DOCTYPE html><html lang="id"><head><title>Kelola Pertemuan LKM</title>' + BASE_STYLE + """</head><body><div id="toast-container"></div>{navbar}<div class="box" style="max-width: 750px;"><h2>Kelola Pertemuan LKM</h2><p>Buat pertemuan terlebih dahulu, lalu klik pertemuan tersebut untuk menambah soal dengan 8 Golongan.</p><form method="POST" style="display: flex; gap: 12px; margin-top: 20px; margin-bottom: 30px;" onsubmit="showLoading('Membuat pertemuan...')"><input type="text" name="nama_pertemuan" placeholder="Nama Pertemuan (Contoh: Pertemuan 1)" required style="margin: 0; flex: 1;"><button type="submit" class="btn btn-success" style="width: auto;">+ Buat Pertemuan</button></form><h3>Daftar Pertemuan</h3>{html_list}</div></body></html>""".replace('{navbar}', render_navbar()).replace('{html_list}', html_list)

@app.route('/guru/bank-soal/lkm/hapus-pertemuan/<int:id_p>')
@login_required
def hapus_pertemuan_lkm(id_p):
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    pertemuan = db.get_or_404(PertemuanLKM, id_p)
    SoalLKM.query.filter_by(pertemuan_id=id_p).delete()
    db.session.delete(pertemuan)
    db.session.commit()
    return redirect(url_for('guru_pertemuan_lkm'))

@app.route('/guru/bank-soal/lkm/detail/<int:id_p>', methods=['GET', 'POST'])
@login_required
def guru_detail_pertemuan_lkm(id_p):
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    pertemuan = db.get_or_404(PertemuanLKM, id_p)
    if request.method == 'POST':
        golongan = request.form.get('golongan')
        pertanyaan = request.form.get('pertanyaan')
        kunci = request.form.get('kunci')
        file_foto = request.files.get('foto_soal')
        nama_foto = None
        if file_foto and file_foto.filename != '':
            if allowed_file(file_foto.filename):
                nama_foto = secure_filename(file_foto.filename)
                file_foto.save(os.path.join(app.config['UPLOAD_FOLDER'], nama_foto))
        soal_baru = SoalLKM(pertemuan_id=id_p, golongan=golongan, pertanyaan=pertanyaan, kunci_jawaban=kunci, foto=nama_foto)
        db.session.add(soal_baru)
        db.session.commit()
        return redirect(url_for('guru_detail_pertemuan_lkm', id_p=id_p))
    
    daftar_soal = SoalLKM.query.filter_by(pertemuan_id=id_p).all()
    html_soal = ''
    for idx, s in enumerate(daftar_soal, 1):
        info_golongan = GOLONGAN_LKM_CONFIG.get(str(s.golongan), {'nama': f'Golongan {s.golongan}'})['nama']
        tampilan_foto = f'<br><img src="/static/uploads/{s.foto}" width="200" style="margin-top:10px; border-radius:8px; border:1px solid var(--border-color);">' if s.foto else ''
        html_soal += f"""
        <div style="background: var(--bg-main); border: 2px solid var(--border-color); padding: 24px; border-radius: 16px; margin-bottom: 25px;">
            <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                <div>
                    <span style="background: #e0e7ff; color: #4338ca; border: 1px solid #c7d2fe; padding: 4px 10px; border-radius: 8px; font-size: 0.75rem; font-weight: 700; display: inline-block; margin-bottom: 8px;">&#127919; {info_golongan}</span><br>
                    <span style="background: var(--primary); color: white; padding: 4px 10px; border-radius: 8px; font-size: 0.8rem; font-weight: 800;">Soal No. {idx}</span>
                    <p style="font-size: 1.05rem; color: var(--text-main); margin-top: 10px; white-space: pre-line;">{s.pertanyaan}</p>
                    {tampilan_foto}
                </div>
                <div style="display:flex; gap:6px;">
                    <a href="/guru/bank-soal/lkm/edit-soal/{s.id}" class="btn btn-warning" style="padding: 6px 12px; font-size: 0.8rem; width: auto;">Edit</a>
                    <a href="/guru/bank-soal/lkm/hapus-soal/{s.id}" class="btn btn-danger" style="padding: 6px 12px; font-size: 0.8rem; width: auto;" onclick="return confirm('Hapus soal ini?')">Hapus</a>
                </div>
            </div>
            <div style="background: var(--card-bg); border: 2px solid var(--border-color); padding: 14px; border-radius: 10px; margin-top: 15px;">
                &#128273; <b>Kunci Jawaban:</b><br>{s.kunci_jawaban}
            </div>
        </div>
        """
    if not html_soal:
        html_soal = '<div class="empty-state"><div class="empty-state-icon">&#128221;</div><div class="empty-state-text">Belum ada soal dalam pertemuan ini.</div></div>'

    options_html = ''
    for key, val in GOLONGAN_LKM_CONFIG.items():
        options_html += f'<option value="{key}">{val["nama"]}</option>'
        
    return '<!DOCTYPE html><html lang="id"><head><title>Kelola Soal LKM</title>' + BASE_STYLE + """</head><body><div id="toast-container"></div>{navbar}<div class="box" style="max-width: 900px;"><h2 style="margin-bottom:15px;">Manajemen Soal: {nama_p}</h2>

<form method="POST" enctype="multipart/form-data" onsubmit="showLoading('Menyimpan soal...')">
    <label>Pilih Kategori Golongan:</label>
    <select name="golongan" required>{options_html}</select>
    
    <div style="display:flex; justify-content:space-between; align-items:center; margin-top:10px;">
        <label style="margin:0;">Pertanyaan:</label>
        <button type="button" class="theme-toggle" onclick="bukaModalSimbol('input-p')" style="font-size:0.75rem; padding:4px 10px;">Sisipkan Simbol Matematika</button>
    </div>
    <textarea name="pertanyaan" id="input-p" onfocus="setTarget(this)" required placeholder="Tuliskan pertanyaan..." style="height:110px;"></textarea>
    
    <label>Gambar Soal (Opsional):</label>
    <input type="file" name="foto_soal" accept="image/*" style="background: var(--card-bg); padding: 10px;">
    
    <div style="display:flex; justify-content:space-between; align-items:center; margin-top:10px;">
        <label style="margin:0;">Kunci Jawaban:</label>
        <button type="button" class="theme-toggle" onclick="bukaModalSimbol('input-k')" style="font-size:0.75rem; padding:4px 10px;">Sisipkan Simbol Matematika</button>
    </div>
    <textarea name="kunci" id="input-k" onfocus="setTarget(this)" required placeholder="Poin kunci jawaban..." style="height:110px;"></textarea>
    
    <button type="submit" class="btn btn-success" style="margin-top:15px;">+ Tambahkan Soal</button>
</form>

<div id="modal-simbol" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(15,23,42,0.6); backdrop-filter:blur(3px); z-index:9999; align-items:center; justify-content:center;">
    <div style="background:var(--card-bg); border:2px solid var(--border-color); padding:25px; border-radius:16px; width:90%; max-width:400px; box-shadow:var(--shadow);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
            <strong style="color:var(--primary);">Pilih Simbol Matematika</strong>
            <button type="button" onclick="tutupModalSimbol()" class="btn btn-danger" style="padding:4px 10px; font-size:0.75rem; width:auto;">Tutup</button>
        </div>
        <div class="calc-grid" style="grid-template-columns: repeat(4, 1fr); gap:8px;">
            <button type="button" class="calc-btn" onclick="pilihSimbol('&sup2;')">x&sup2;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbol('&sup3;')">x&sup3;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbol('&radic;')">&radic;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbol('&pi;')">&pi;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbol('&deg;')">&deg;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbol('&asymp;')">&asymp;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbol('&ne;')">&ne;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbol('&le;')">&le;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbol('&ge;')">&ge;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbol('*')">*</button>
            <button type="button" class="calc-btn" onclick="pilihSimbol('/')">/</button>
            <button type="button" class="calc-btn" onclick="pilihSimbol('&plusmn;')">&plusmn;</button>
        </div>
    </div>
</div>

<script>
let activeEl = null;
function setTarget(el) { activeEl = el; }

function bukaModalSimbol(idTarget) {
    activeEl = document.getElementById(idTarget);
    document.getElementById('modal-simbol').style.display = 'flex';
}
function tutupModalSimbol() {
    document.getElementById('modal-simbol').style.display = 'none';
}
function pilihSimbol(sym) {
    if(activeEl) {
        const start = activeEl.selectionStart;
        const end = activeEl.selectionEnd;
        const val = activeEl.value;
        activeEl.value = val.substring(0, start) + sym + val.substring(end);
        activeEl.selectionStart = activeEl.selectionEnd = start + sym.length;
        activeEl.focus();
    }
    tutupModalSimbol();
}
</script>

<h3 style="margin-top: 40px; border-bottom: 2px solid var(--border-color); padding-bottom: 10px;">Daftar Soal</h3>{html_soal}</div></body></html>""".replace('{navbar}', render_navbar()).replace('{nama_p}', pertemuan.nama_pertemuan).replace('{options_html}', options_html).replace('{html_soal}', html_soal)

@app.route('/guru/bank-soal/lkm/edit-soal/<int:id_s>', methods=['GET', 'POST'])
@login_required
def guru_edit_soal_lkm(id_s):
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    soal = db.get_or_404(SoalLKM, id_s)
    if request.method == 'POST':
        soal.golongan = request.form.get('golongan')
        soal.pertanyaan = request.form.get('pertanyaan')
        soal.kunci_jawaban = request.form.get('kunci')
        file_foto = request.files.get('foto_soal')
        if file_foto and file_foto.filename != '':
            if allowed_file(file_foto.filename):
                nama_foto = secure_filename(file_foto.filename)
                file_foto.save(os.path.join(app.config['UPLOAD_FOLDER'], nama_foto))
                soal.foto = nama_foto
        db.session.commit()
        return redirect(url_for('guru_detail_pertemuan_lkm', id_p=soal.pertemuan_id))
        
    options_html = ''
    for key, val in GOLONGAN_LKM_CONFIG.items():
        sel = 'selected' if str(soal.golongan) == key else ''
        options_html += f'<option value="{key}" {sel}>{val["nama"]}</option>'
        
    tampilan_foto_info = f'<br><img src="/static/uploads/{soal.foto}" width="200" style="margin-top:10px; border-radius:8px; border:1px solid var(--border-color);">' if soal.foto else '<p style="font-size: 0.85rem; color: var(--text-muted);">Tidak ada gambar terlampir.</p>'
    
    return '<!DOCTYPE html><html lang="id"><head><title>Edit Soal LKM</title>' + BASE_STYLE + """</head><body><div id="toast-container"></div>{navbar}<div class="box"><h2 style="margin-bottom:15px;">Edit Soal LKM</h2><form method="POST" enctype="multipart/form-data" onsubmit="showLoading('Memperbarui soal...')"><label>Pilih Kategori Golongan:</label><select name="golongan" required>{options_html}</select><label>Pertanyaan:</label><textarea name="pertanyaan" required style="height:120px;">{pertanyaan}</textarea><label>Gambar Soal Saat Ini:</label>{tampilan_foto_info}<label style="margin-top:15px;">Ganti / Unggah Gambar Baru (Opsional):</label><input type="file" name="foto_soal" accept="image/*" style="background: var(--card-bg); padding: 10px;"><label>Kunci Jawaban:</label><textarea name="kunci" required style="height:120px;">{kunci}</textarea><button type="submit" class="btn btn-warning" style="margin-top:10px;">Simpan Perubahan</button></form></div></body></html>""".replace('{navbar}', render_navbar()).replace('{options_html}', options_html).replace('{pertanyaan}', soal.pertanyaan).replace('{kunci}', soal.kunci_jawaban).replace('{tampilan_foto_info}', tampilan_foto_info)

@app.route('/guru/bank-soal/lkm/hapus-soal/<int:id_s>')
@login_required
def hapus_soal_lkm(id_s):
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    soal = db.get_or_404(SoalLKM, id_s)
    p_id = soal.pertemuan_id
    db.session.delete(soal)
    db.session.commit()
    return redirect(url_for('guru_detail_pertemuan_lkm', id_p=p_id))

@app.route('/guru/bank-soal/<kategori>', methods=['GET', 'POST'])
@login_required
def guru_soal_lain(kategori):
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    if kategori not in ['latihan', 'evaluasi']:
        return redirect(url_for('bank_soal'))
    
    if request.method == 'POST':
        pertanyaan = request.form.get('pertanyaan')
        kunci = request.form.get('kunci')
        file_foto = request.files.get('foto_soal')
        nama_foto = None
        if file_foto and file_foto.filename != '':
            if allowed_file(file_foto.filename):
                nama_foto = secure_filename(file_foto.filename)
                file_foto.save(os.path.join(app.config['UPLOAD_FOLDER'], nama_foto))
        soal_baru = SoalLain(kategori=kategori, pertanyaan=pertanyaan, kunci_jawaban=kunci, foto=nama_foto)
        db.session.add(soal_baru)
        db.session.commit()
        return redirect(url_for('guru_soal_lain', kategori=kategori))
        
    daftar_soal = SoalLain.query.filter_by(kategori=kategori).all()
    html_soal = ''
    for idx, s in enumerate(daftar_soal, 1):
        tampilan_foto = f'<br><img src="/static/uploads/{s.foto}" width="200" style="margin-top:10px; border-radius:8px; border:1px solid var(--border-color);">' if s.foto else ''
        html_soal += f"""
        <div style="background: var(--bg-main); border: 2px solid var(--border-color); padding: 24px; border-radius: 16px; margin-bottom: 25px;">
            <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                <div>
                    <span style="background: var(--primary); color: white; padding: 4px 10px; border-radius: 8px; font-size: 0.8rem; font-weight: 800;">Soal No. {idx}</span>
                    <p style="font-size: 1.05rem; color: var(--text-main); margin-top: 10px; white-space: pre-line;">{s.pertanyaan}</p>
                    {tampilan_foto}
                </div>
                <div style="display:flex; gap:6px;">
                    <a href="/guru/bank-soal/{kategori}/edit/{s.id}" class="btn btn-warning" style="padding: 6px 12px; font-size: 0.8rem; width: auto;">Edit</a>
                    <a href="/guru/bank-soal/{kategori}/hapus/{s.id}" class="btn btn-danger" style="padding: 6px 12px; font-size: 0.8rem; width: auto;" onclick="return confirm('Hapus soal ini?')">Hapus</a>
                </div>
            </div>
            <div style="background: var(--card-bg); border: 2px solid var(--border-color); padding: 14px; border-radius: 10px; margin-top: 15px;">
                &#128273; <b>Kunci Jawaban:</b><br>{s.kunci_jawaban}
            </div>
        </div>
        """
    if not html_soal:
        html_soal = '<div class="empty-state"><div class="empty-state-icon">&#128221;</div><div class="empty-state-text">Belum ada soal dalam kategori ini.</div></div>'

    judul_kat = 'Soal Latihan' if kategori == 'latihan' else 'Soal Evaluasi'
    return '<!DOCTYPE html><html lang="id"><head><title>Manajemen Soal</title>' + BASE_STYLE + """</head><body><div id="toast-container"></div>{navbar}<div class="box"><h2 style="margin-bottom:15px;">Manajemen {judul_kat}</h2><form method="POST" enctype="multipart/form-data" onsubmit="showLoading('Menambahkan soal...')"><label>Pertanyaan:</label><textarea name="pertanyaan" required placeholder="Tuliskan pertanyaan..." style="height:110px;"></textarea><label>Gambar Soal (Opsional):</label><input type="file" name="foto_soal" accept="image/*" style="background: var(--card-bg); padding: 10px;"><label>Kunci Jawaban:</label><textarea name="kunci" required placeholder="Poin kunci jawaban..." style="height:110px;"></textarea><button type="submit" class="btn btn-success">+ Tambahkan Soal</button></form><h3 style="margin-top: 40px; border-bottom: 2px solid var(--border-color); padding-bottom: 10px;">Daftar Soal</h3>{html_soal}</div></body></html>""".replace('{navbar}', render_navbar()).replace('{judul_kat}', judul_kat).replace('{html_soal}', html_soal)

@app.route('/guru/bank-soal/<kategori>/edit/<int:id_s>', methods=['GET', 'POST'])
@login_required
def guru_edit_soal_lain(kategori, id_s):
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    soal = db.get_or_404(SoalLain, id_s)
    if request.method == 'POST':
        soal.pertanyaan = request.form.get('pertanyaan')
        soal.kunci_jawaban = request.form.get('kunci')
        file_foto = request.files.get('foto_soal')
        if file_foto and file_foto.filename != '':
            if allowed_file(file_foto.filename):
                nama_foto = secure_filename(file_foto.filename)
                file_foto.save(os.path.join(app.config['UPLOAD_FOLDER'], nama_foto))
                soal.foto = nama_foto
        db.session.commit()
        return redirect(url_for('guru_soal_lain', kategori=kategori))
        
    tampilan_foto_info = f'<br><img src="/static/uploads/{soal.foto}" width="200" style="margin-top:10px; border-radius:8px; border:1px solid var(--border-color);">' if soal.foto else '<p style="font-size: 0.85rem; color: var(--text-muted);">Tidak ada gambar terlampir.</p>'
    judul_kat = 'Soal Latihan' if kategori == 'latihan' else 'Soal Evaluasi'
    return '<!DOCTYPE html><html lang="id"><head><title>Edit Soal</title>' + BASE_STYLE + """</head><body><div id="toast-container"></div>{navbar}<div class="box"><h2 style="margin-bottom:15px;">Edit Soal {judul_kat}</h2><form method="POST" enctype="multipart/form-data" onsubmit="showLoading('Memperbarui soal...')"><label>Pertanyaan:</label><textarea name="pertanyaan" required style="height:120px;">{pertanyaan}</textarea><label>Gambar Soal Saat Ini:</label>{tampilan_foto_info}<label style="margin-top:15px;">Ganti / Unggah Gambar Baru (Opsional):</label><input type="file" name="foto_soal" accept="image/*" style="background: var(--card-bg); padding: 10px;"><label>Kunci Jawaban:</label><textarea name="kunci" required style="height:120px;">{kunci}</textarea><button type="submit" class="btn btn-warning" style="margin-top:10px;">Simpan Perubahan</button></form></div></body></html>""".replace('{navbar}', render_navbar()).replace('{judul_kat}', judul_kat).replace('{pertanyaan}', soal.pertanyaan).replace('{kunci}', soal.kunci_jawaban).replace('{tampilan_foto_info}', tampilan_foto_info)

@app.route('/guru/bank-soal/<kategori>/hapus/<int:id_s>')
@login_required
def hapus_soal_lain(kategori, id_s):
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    soal = db.get_or_404(SoalLain, id_s)
    db.session.delete(soal)
    db.session.commit()
    return redirect(url_for('guru_soal_lain', kategori=kategori))

@app.route('/siswa/kerjakan/<kategori>', methods=['GET', 'POST'])
@login_required
def kerjakan_tugas_umum(kategori):
    if current_user.role != 'siswa':
        return 'Akses ditolak!'
    
    user_name = current_user.nama or current_user.username
    
    sudah_kumpul = JawabanSiswa.query.filter_by(nama_siswa=user_name, kategori=kategori).first()
    if sudah_kumpul:
        return '<script>alert("Anda sudah mengumpulkan ujian/tugas ini! Akses ditutup. Hubungi guru jika ingin membuka kembali.");window.location="/siswa/pilih-ujian";</script>'
    
    if kategori == 'evaluasi':
        ujian = PengaturanUjian.query.filter_by(nama_ujian='Ujian Evaluasi').first()
        if ujian.max_percobaan > 0:
            jumlah_percobaan_siswa = JawabanSiswa.query.filter_by(nama_siswa=user_name, kategori='evaluasi').count()
            if jumlah_percobaan_siswa >= ujian.max_percobaan:
                return '<script>alert("Anda telah mencapai batas maksimal percobaan ujian ini!");window.location="/siswa/pilih-ujian";</script>'
    
    if kategori in ['latihan', 'evaluasi']:
        daftar_pertemuan = PertemuanLKM.query.all()
        semua_lulus = True
        for p in daftar_pertemuan:
            t_p = JawabanSiswa.query.filter_by(nama_siswa=user_name, tugas=f"LKM - {p.nama_pertemuan}").first()
            if not t_p or t_p.nilai_angka is None or t_p.nilai_angka < 75:
                semua_lulus = False
                break
        if not semua_lulus:
            return '<script>alert("Akses ditolak! Selesaikan seluruh pertemuan LKM dengan nilai minimal 75.");window.location="/siswa/pilih-ujian";</script>'

    if kategori == 'latihan':
        soals = SoalLain.query.filter_by(kategori='latihan').all()
        daftar_soal = [{'pertanyaan': s.pertanyaan, 'kunci': s.kunci_jawaban, 'foto': s.foto, 'golongan': 'Umum'} for s in soals]
        nama_tugas_lengkap = 'Soal Latihan Mandiri'
    else:
        soals = SoalLain.query.filter_by(kategori='evaluasi').all()
        daftar_soal = [{'pertanyaan': s.pertanyaan, 'kunci': s.kunci_jawaban, 'foto': s.foto, 'golongan': 'Umum'} for s in soals]
        nama_tugas_lengkap = 'Ujian Evaluasi'

    pesan_status_ujian = ''
    bisa_kirim = True
    waktu_sekarang = datetime.now()
    info_durasi = ''
    sisa_waktu_detik = 0

    if kategori == 'evaluasi':
        ujian = PengaturanUjian.query.filter_by(nama_ujian='Ujian Evaluasi').first()
        if ujian.status == 'tutup':
            pesan_status_ujian = '<span style="color: #f43f5e; font-weight: bold;">Ujian Evaluasi saat ini DITUTUP oleh Guru.</span>'
            bisa_kirim = False
        elif ujian.status == 'buka_selalu':
            pesan_status_ujian = '<span style="color: #10b981; font-weight: bold;">Ujian Evaluasi DIBUKA setiap saat.</span>'
        elif ujian.status == 'jadwal':
            if ujian.waktu_mulai and ujian.waktu_selesai:
                waktu_mulai_dt = datetime.strptime(ujian.waktu_mulai, '%Y-%m-%dT%H:%M')
                waktu_selesai_dt = datetime.strptime(ujian.waktu_selesai, '%Y-%m-%dT%H:%M')
                if waktu_sekarang < waktu_mulai_dt:
                    pesan_status_ujian = f'<span style="color: #f59e0b; font-weight: bold;">Ujian belum dimulai. Mulai pada: {ujian.waktu_mulai.replace("T", " ")}</span>'
                    bisa_kirim = False
                elif waktu_sekarang > waktu_selesai_dt:
                    pesan_status_ujian = '<span style="color: #f43f5e; font-weight: bold;">Waktu ujian telah BERAKHIR.</span>'
                    bisa_kirim = False
                else:
                    pesan_status_ujian = f'<span style="color: #10b981; font-weight: bold;">Ujian SEDANG BERLANGSUNG</span>'
            else:
                pesan_status_ujian = '<span style="color: #f43f5e;">Jadwal belum diatur lengkap oleh guru.</span>'
                bisa_kirim = False

        if bisa_kirim and ujian.durasi_menit > 0:
            session_key = f'waktu_mulai_evaluasi_{current_user.id}'
            if session_key not in session:
                session[session_key] = datetime.now().isoformat()
            
            waktu_mulai_dt = datetime.fromisoformat(session[session_key])
            elapsed = (datetime.now() - waktu_mulai_dt).total_seconds()
            sisa_waktu_detik = int(max(0, (ujian.durasi_menit * 60) - elapsed))
            
            if sisa_waktu_detik <= 0:
                bisa_kirim = False
        info_durasi = f'<b>Durasi Pengerjaan:</b> {ujian.durasi_menit} Menit' if ujian.durasi_menit > 0 else '<b>Durasi Pengerjaan:</b> Tanpa Batasan Waktu'
    else:
        ujian = type('obj', (object,), {'durasi_menit': 0})()

    if request.method == 'POST':
        if kategori == 'evaluasi' and not bisa_kirim:
            return '<script>alert("Maaf, waktu ujian telah habis atau ujian ditutup!");window.location="/siswa/pilih-ujian";</script>'
        
        jawaban_gabungan = []
        for i, s in enumerate(daftar_soal):
            j_teks = request.form.get(f'jawaban_{i}', '')
            jawaban_gabungan.append(f"Soal {i+1}: ({s['pertanyaan']})\nJawaban: {j_teks}")
        
        jawaban_final_str = "\n\n-------------------\n\n".join(jawaban_gabungan)
        
        file_foto = request.files.get('foto')
        nama_file_foto = None
        if file_foto and file_foto.filename != '':
            if allowed_file(file_foto.filename):
                nama_file_foto = secure_filename(file_foto.filename)
                file_foto.save(os.path.join(app.config['UPLOAD_FOLDER'], nama_file_foto))
            else:
                return '<script>alert("Hanya file gambar (JPG/PNG/GIF) yang diizinkan!");history.back();</script>'
            
        jumlah_kecurangan = int(request.form.get('jumlah_kecurangan', 0))
        durasi_kecurangan_detik = int(request.form.get('durasi_kecurangan', 0))
        if durasi_kecurangan_detik >= 60:
            durasi_str = f"{durasi_kecurangan_detik // 60} menit {durasi_kecurangan_detik % 60} detik"
        else:
            durasi_str = f"{durasi_kecurangan_detik} detik"

        kirim_tugas = JawabanSiswa(
            nama_siswa=user_name,
            tugas=nama_tugas_lengkap,
            kategori=kategori,
            jawaban=jawaban_final_str,
            foto=nama_file_foto,
            jumlah_kecurangan=jumlah_kecurangan,
            durasi_kecurangan_str=durasi_str,
            evaluasi_ai='Menunggu penilaian dan analisis guru/AI...'
        )
        db.session.add(kirim_tugas)
        db.session.commit()
        
        if kategori == 'evaluasi':
            session.pop(f'waktu_mulai_evaluasi_{current_user.id}', None)
            
        return '<script>localStorage.removeItem("draft_ujian_' + kategori + '");alert("Jawaban berhasil dikirim!");window.location="/siswa/riwayat";</script>'

    status_info_html = f'<p>{pesan_status_ujian}</p><p>{info_durasi}</p>' if kategori == 'evaluasi' else '<p style="color: #10b981; font-weight: bold;">Status: Dibuka & Siap Dikerjakan (Auto-save Aktif)</p>'

    form_soal_html = ''
    nav_palet_html = ''
    for idx, s in enumerate(daftar_soal):
        img_tag = f'<br><img src="/static/uploads/{s["foto"]}" width="250" style="margin-top:10px; border-radius:8px; border:1px solid var(--border-color);">' if s['foto'] else ''
        nav_palet_html += f'<button type="button" id="palet-btn-{idx}" onclick="lompatKeSoal({idx})" style="width:38px; height:38px; border-radius:8px; border:2px solid var(--border-color); background:var(--card-bg); color:var(--text-main); font-weight:700; cursor:pointer;">{idx+1}</button>'
        
        form_soal_html += f"""
        <div id="card-soal-{idx}" style="background: var(--bg-main); padding: 25px; border-radius: 14px; border: 2px solid var(--border-color); margin-bottom: 25px; text-align: left;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                <strong style="color: var(--primary);">Soal No. {idx+1} dari {len(daftar_soal)}</strong>
            </div>
            <p style="white-space: pre-line; color: var(--text-main); font-size: 1.05rem;">{s['pertanyaan']}</p>
            {img_tag}
            <br><label><b>Jawaban Anda:</b></label>
            <textarea name="jawaban_{idx}" id="jawaban_{idx}" rows="4" onfocus="setTarget(this)" oninput="simpanDraft(); cekTerisi({idx})" placeholder="Tuliskan jawaban Anda..." style="width: 100%; padding: 12px; margin-top: 5px;"></textarea>
        </div>
        """

    if not form_soal_html:
        form_soal_html = '<div class="empty-state"><div class="empty-state-icon">&#128221;</div><div class="empty-state-text">Belum ada soal tersedia untuk modul ini.</div></div>'

    tampil_timer_val = 'block' if (kategori == 'evaluasi' and ujian.durasi_menit > 0) else 'none'

    return render_template_string(
        '<!DOCTYPE html><html lang="id"><head><title>Kerjakan Ujian</title>' + BASE_STYLE + '''</head><body><div id="toast-container"></div>''' + render_navbar() + '''<div class="box" style="max-width: 900px; text-align: center;"><h2 style="margin-bottom:15px;">Kerjakan: ''' + nama_tugas_lengkap + '''</h2>

<div id="timer-box" style="background: #fff1f2; border: 2px solid #fecaca; color: #e11d48; padding: 12px; border-radius: 12px; font-weight: 800; margin-bottom: 20px; display: ''' + tampil_timer_val + ''';">
    Sisa Waktu Ujian: <span id="timer-display">--:--</span>
</div>

<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 15px; flex-wrap:wrap; gap:10px;">
    <div style="background: var(--card-bg); border: 2px solid var(--border-color); padding: 10px 15px; border-radius: 12px; text-align: left; flex:1;">
        <strong style="font-size: 0.85rem; display: block; margin-bottom: 6px;">Palet Nomor Soal:</strong>
        <div style="display: flex; flex-wrap: wrap; gap: 6px;">
            ''' + nav_palet_html + '''
        </div>
    </div>
    <button type="button" class="btn btn-warning" onclick="bukaModalSimbolSiswa()" style="width:auto; padding:12px 18px; font-size:0.9rem;">Simbol & Rumus</button>
</div>

<div id="modal-simbol-siswa" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(15,23,42,0.6); backdrop-filter:blur(3px); z-index:9999; align-items:center; justify-content:center;">
    <div style="background:var(--card-bg); border:2px solid var(--border-color); padding:25px; border-radius:16px; width:90%; max-width:420px; box-shadow:var(--shadow); text-align:left;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
            <strong style="color:var(--primary);">Simbol & Hitung Cepat</strong>
            <button type="button" onclick="tutupModalSimbolSiswa()" class="btn btn-danger" style="padding:4px 10px; font-size:0.75rem; width:auto;">Tutup</button>
        </div>
        <p style="font-size:0.8rem; color:var(--text-muted); margin-top:0;">Klik simbol di bawah untuk memasukkan ke kotak jawaban:</p>
        <div class="calc-grid" style="grid-template-columns: repeat(4, 1fr); gap:8px; margin-bottom:15px;">
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&sup2;')">x&sup2;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&sup3;')">x&sup3;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&radic;')">&radic;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&pi;')">&pi;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&deg;')">&deg;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&asymp;')">&asymp;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&ne;')">&ne;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&le;')">&le;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&ge;')">&ge;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('*')">*</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('/')">/</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&plusmn;')">&plusmn;</button>
        </div>
        <hr style="border:0; border-top:1px solid var(--border-color); margin:15px 0;">
        <label style="font-size:0.85rem;">Kalkulator Hitung Cepat:</label>
        <div style="margin-top: 5px; display: flex; gap: 6px;">
            <input type="text" id="calc-input" placeholder="Contoh: 3*3 + 4*4" style="margin: 0; font-size: 0.85rem; padding: 8px;">
            <button type="button" class="btn" style="width: auto; padding: 8px 12px; font-size: 0.85rem;" onclick="hitungCepat()">Hitung</button>
            <input type="text" id="calc-hasil" readonly placeholder="Hasil" style="margin: 0; width: 90px; font-weight: 700; text-align: center; background: var(--card-bg); padding: 8px; font-size: 0.85rem;">
        </div>
    </div>
</div>

<div id="modal-konfirmasi-kirim" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(15,23,42,0.6); backdrop-filter:blur(3px); z-index:9999; align-items:center; justify-content:center;">
    <div style="background:var(--card-bg); border:2px solid var(--border-color); padding:30px; border-radius:16px; width:90%; max-width:420px; box-shadow:var(--shadow); text-align:center;">
        <div style="font-size:3rem; margin-bottom:10px;">&#9888;</div>
        <h3 style="margin-bottom:10px;">Konfirmasi Pengiriman Ujian</h3>
        <p style="font-size:0.9rem; color:var(--text-muted); margin-bottom:20px;">Apakah Anda yakin ingin mengirimkan seluruh jawaban ini?</p>
        <div style="display:flex; gap:10px;">
            <button type="button" onclick="tutupKonfirmasiKirim()" class="btn btn-secondary" style="flex:1;">Periksa Lagi</button>
            <button type="button" onclick="eksekusiKirimUjian()" class="btn btn-success" style="flex:1;">Ya, Kirim Sekarang</button>
        </div>
    </div>
</div>

<div style="background: var(--card-bg); padding: 25px; border-radius: 14px; border: 2px solid var(--border-color); text-align: left;">
    ''' + status_info_html + '''
    <form id="form-ujian" method="POST" enctype="multipart/form-data">
        <input type="hidden" name="jumlah_kecurangan" id="input-kecurangan" value="0">
        <input type="hidden" name="durasi_kecurangan" id="input-durasi-kecurangan" value="0">
        ''' + form_soal_html + '''
        <label style="margin-top: 15px; display:block;"><b>Unggah Foto Pendukung Keseluruhan (Opsional):</b></label>
        <input type="file" name="foto" accept="image/*" style="background: var(--card-bg); padding: 12px; margin-bottom: 25px;">
        <button type="button" class="btn btn-success" onclick="bukaKonfirmasiKirim()" style="padding: 16px; font-size: 1.05rem;">Kirim Semua Jawaban</button>
    </form>
</div>

<script>
let activeTa = null;
function setTarget(el) { activeTa = el; }
function bukaModalSimbolSiswa() { document.getElementById('modal-simbol-siswa').style.display = 'flex'; }
function tutupModalSimbolSiswa() { document.getElementById('modal-simbol-siswa').style.display = 'none'; }
function pilihSimbolSiswa(sym) {
    if(!activeTa) { const tas = document.querySelectorAll('textarea'); if(tas.length > 0) activeTa = tas[0]; }
    if(activeTa) {
        const start = activeTa.selectionStart, end = activeTa.selectionEnd, val = activeTa.value;
        activeTa.value = val.substring(0, start) + sym + val.substring(end);
        activeTa.selectionStart = activeTa.selectionEnd = start + sym.length;
        activeTa.focus();
        simpanDraft();
    }
    tutupModalSimbolSiswa();
}
function bukaKonfirmasiKirim() { document.getElementById('modal-konfirmasi-kirim').style.display = 'flex'; }
function tutupKonfirmasiKirim() { document.getElementById('modal-konfirmasi-kirim').style.display = 'none'; }
function eksekusiKirimUjian() {
    tutupKonfirmasiKirim();
    if (waktuMulaiKeluar !== null) { totalDurasiKeluar += Math.floor((Date.now() - waktuMulaiKeluar) / 1000); document.getElementById('input-durasi-kecurangan').value = totalDurasiKeluar; }
    localStorage.removeItem(draftKey);
    showLoading('Mengirimkan jawaban...');
    document.getElementById('form-ujian').submit();
}
const draftKey = "draft_ujian_''' + kategori + '''";
function simpanDraft() {
    const tas = document.querySelectorAll('textarea');
    let dataDraft = {};
    tas.forEach((ta, i) => { dataDraft[i] = ta.value; });
    localStorage.setItem(draftKey, JSON.stringify(dataDraft));
}
document.addEventListener('DOMContentLoaded', () => {
    const tas = document.querySelectorAll('textarea');
    if(tas.length > 0) activeTa = tas[0];
    const saved = localStorage.getItem(draftKey);
    if(saved) {
        try {
            const dataDraft = JSON.parse(saved);
            tas.forEach((ta, i) => { if(dataDraft[i] !== undefined) { ta.value = dataDraft[i]; cekTerisi(i); } });
        } catch(e) {}
    }
});
function hitungCepat() {
    try {
        let inputVal = document.getElementById('calc-input').value;
        let cleaned = inputVal.replace(/[\\u00D7]/g, '*').replace(/[\\u00F7]/g, '/');
        const res = eval(cleaned);
        document.getElementById('calc-hasil').value = res;
    } catch(e) { document.getElementById('calc-hasil').value = "Error"; }
}
function lompatKeSoal(idx) { document.getElementById('card-soal-' + idx).scrollIntoView({ behavior: 'smooth', block: 'center' }); }
function cekTerisi(idx) {
    const val = document.getElementById('jawaban_' + idx).value.trim(), btn = document.getElementById('palet-btn-' + idx);
    if(val.length > 0) { btn.style.background = 'var(--success)'; btn.style.color = 'white'; btn.style.borderColor = 'var(--success)'; }
    else { btn.style.background = 'var(--card-bg)'; btn.style.color = 'var(--text-main)'; btn.style.borderColor = 'var(--border-color)'; }
}
let kecuranganCount = 0, totalDurasiKeluar = 0, waktuMulaiKeluar = null;
document.addEventListener("visibilitychange", () => {
    if (document.hidden) { kecuranganCount++; waktuMulaiKeluar = Date.now(); document.getElementById('input-kecurangan').value = kecuranganCount; showToast("Peringatan: Anda meninggalkan halaman ujian!", true); }
    else if (waktuMulaiKeluar !== null) { totalDurasiKeluar += Math.floor((Date.now() - waktuMulaiKeluar) / 1000); waktuMulaiKeluar = null; document.getElementById('input-durasi-kecurangan').value = totalDurasiKeluar; }
});
let waktu = ''' + str(sisa_waktu_detik) + ''';
if (waktu > 0 && "''' + tampil_timer_val + '''" === 'block') {
    let hitungMundur = setInterval(() => {
        let m = Math.floor(waktu / 60), s = waktu % 60;
        document.getElementById('timer-display').innerText = (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
        if (waktu <= 0) {
            clearInterval(hitungMundur);
            alert("Waktu Ujian Telah Habis!");
            if (waktuMulaiKeluar !== null) { totalDurasiKeluar += Math.floor((Date.now() - waktuMulaiKeluar) / 1000); document.getElementById('input-durasi-kecurangan').value = totalDurasiKeluar; }
            localStorage.removeItem(draftKey);
            showLoading('Waktu habis, mengirim otomatis...');
            document.getElementById('form-ujian').submit();
        }
        waktu--;
    }, 1000);
}
</script>
</div></body></html>'''
    )

@app.route('/siswa/kerjakan/lkm/<int:id_p>', methods=['GET', 'POST'])
@login_required
def kerjakan_lkm_pertemuan(id_p):
    if current_user.role != 'siswa':
        return 'Akses ditolak!'
    
    user_name = current_user.nama or current_user.username
    pertemuan = db.get_or_404(PertemuanLKM, id_p)
    nama_tugas_lengkap = f"LKM - {pertemuan.nama_pertemuan}"
    
    sudah_kumpul = JawabanSiswa.query.filter_by(nama_siswa=user_name, tugas=nama_tugas_lengkap).first()
    if sudah_kumpul:
        return f'<script>alert("Anda sudah mengumpulkan LKM {pertemuan.nama_pertemuan}! Akses ditutup. Hubungi guru jika ingin membuka kembali.");window.location="/siswa/pilih-ujian";</script>'

    soals = SoalLKM.query.filter_by(pertemuan_id=id_p).all()
    daftar_soal = []
    for s in soals:
        info_golongan = GOLONGAN_LKM_CONFIG.get(str(s.golongan), {'nama': f'Golongan {s.golongan}'})['nama']
        daftar_soal.append({
            'id': s.id,
            'pertanyaan': s.pertanyaan,
            'kunci': s.kunci_jawaban,
            'foto': s.foto,
            'golongan': info_golongan
        })

    if request.method == 'POST':
        jawaban_gabungan = []
        for i, s in enumerate(daftar_soal):
            j_teks = request.form.get(f'jawaban_{i}', '')
            jawaban_gabungan.append(f"Soal {i+1} [{s['golongan']}]: ({s['pertanyaan']})\nJawaban: {j_teks}")
        
        jawaban_final_str = "\n\n-------------------\n\n".join(jawaban_gabungan)
        
        file_foto = request.files.get('foto')
        nama_file_foto = None
        if file_foto and file_foto.filename != '':
            if allowed_file(file_foto.filename):
                nama_file_foto = secure_filename(file_foto.filename)
                file_foto.save(os.path.join(app.config['UPLOAD_FOLDER'], nama_file_foto))
            else:
                return '<script>alert("Hanya file gambar (JPG/PNG/GIF) yang diizinkan!");history.back();</script>'
            
        jumlah_kecurangan = int(request.form.get('jumlah_kecurangan', 0))
        durasi_kecurangan_detik = int(request.form.get('durasi_kecurangan', 0))
        durasi_str = f"{durasi_kecurangan_detik // 60} menit {durasi_kecurangan_detik % 60} detik" if durasi_kecurangan_detik >= 60 else f"{durasi_kecurangan_detik} detik"

        kirim_tugas = JawabanSiswa(
            nama_siswa=user_name,
            tugas=nama_tugas_lengkap,
            kategori='lkm',
            jawaban=jawaban_final_str,
            foto=nama_file_foto,
            jumlah_kecurangan=jumlah_kecurangan,
            durasi_kecurangan_str=durasi_str,
            evaluasi_ai='Menunggu penilaian dan analisis guru/AI...'
        )
        db.session.add(kirim_tugas)
        db.session.commit()
        
        return f'<script>localStorage.removeItem("draft_lkm_{id_p}");alert("Jawaban {pertemuan.nama_pertemuan} berhasil dikirim!");window.location="/siswa/pilih-ujian";</script>'

    form_soal_html = ''
    nav_palet_html = ''
    for idx, s in enumerate(daftar_soal):
        img_tag = f'<br><img src="/static/uploads/{s["foto"]}" width="250" style="margin-top:10px; border-radius:8px; border:1px solid var(--border-color);">' if s['foto'] else ''
        gol_badge = f'<span style="background: #e0e7ff; color: #4338ca; padding: 3px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 700;">&#127919; {s["golongan"]}</span><br>'
        
        nav_palet_html += f'<button type="button" id="palet-btn-{idx}" onclick="lompatKeSoal({idx})" style="width:38px; height:38px; border-radius:8px; border:2px solid var(--border-color); background:var(--card-bg); color:var(--text-main); font-weight:700; cursor:pointer;">{idx+1}</button>'
        
        form_soal_html += f"""
        <div id="card-soal-{idx}" style="background: var(--bg-main); padding: 25px; border-radius: 14px; border: 2px solid var(--border-color); margin-bottom: 25px; text-align: left;">
            {gol_badge}
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                <strong style="color: var(--primary);">Soal No. {idx+1} dari {len(daftar_soal)}</strong>
            </div>
            <p style="white-space: pre-line; color: var(--text-main); font-size: 1.05rem;">{s['pertanyaan']}</p>
            {img_tag}
            <br><label><b>Jawaban Anda:</b></label>
            <textarea name="jawaban_{idx}" id="jawaban_{idx}" rows="4" onfocus="setTarget(this)" oninput="simpanDraft(); cekTerisi({idx})" placeholder="Tuliskan jawaban Anda..." style="width: 100%; padding: 12px; margin-top: 5px;"></textarea>
        </div>
        """

    if not form_soal_html:
        form_soal_html = '<div class="empty-state"><div class="empty-state-icon">&#128221;</div><div class="empty-state-text">Belum ada soal tersedia untuk pertemuan ini.</div></div>'

    return render_template_string(
        '<!DOCTYPE html><html lang="id"><head><title>Kerjakan LKM</title>' + BASE_STYLE + '''</head><body><div id="toast-container"></div>''' + render_navbar() + '''<div class="box" style="max-width: 900px; text-align: center;"><h2 style="margin-bottom:15px;">Kerjakan: ''' + nama_tugas_lengkap + '''</h2>

<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 15px; flex-wrap:wrap; gap:10px;">
    <div style="background: var(--card-bg); border: 2px solid var(--border-color); padding: 10px 15px; border-radius: 12px; text-align: left; flex:1;">
        <strong style="font-size: 0.85rem; display: block; margin-bottom: 6px;">Palet Nomor Soal:</strong>
        <div style="display: flex; flex-wrap: wrap; gap: 6px;">
            ''' + nav_palet_html + '''
        </div>
    </div>
    <button type="button" class="btn btn-warning" onclick="bukaModalSimbolSiswa()" style="width:auto; padding:12px 18px; font-size:0.9rem;">Simbol & Rumus</button>
</div>

<div id="modal-simbol-siswa" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(15,23,42,0.6); backdrop-filter:blur(3px); z-index:9999; align-items:center; justify-content:center;">
    <div style="background:var(--card-bg); border:2px solid var(--border-color); padding:25px; border-radius:16px; width:90%; max-width:420px; box-shadow:var(--shadow); text-align:left;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
            <strong style="color:var(--primary);">Simbol & Hitung Cepat</strong>
            <button type="button" onclick="tutupModalSimbolSiswa()" class="btn btn-danger" style="padding:4px 10px; font-size:0.75rem; width:auto;">Tutup</button>
        </div>
        <p style="font-size:0.8rem; color:var(--text-muted); margin-top:0;">Klik simbol di bawah untuk memasukkan ke kotak jawaban:</p>
        <div class="calc-grid" style="grid-template-columns: repeat(4, 1fr); gap:8px; margin-bottom:15px;">
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&sup2;')">x&sup2;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&sup3;')">x&sup3;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&radic;')">&radic;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&pi;')">&pi;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&deg;')">&deg;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&asymp;')">&asymp;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&ne;')">&ne;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&le;')">&le;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&ge;')">&ge;</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('*')">*</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('/')">/</button>
            <button type="button" class="calc-btn" onclick="pilihSimbolSiswa('&plusmn;')">&plusmn;</button>
        </div>
        <hr style="border:0; border-top:1px solid var(--border-color); margin:15px 0;">
        <label style="font-size:0.85rem;">Kalkulator Hitung Cepat:</label>
        <div style="margin-top: 5px; display: flex; gap: 6px;">
            <input type="text" id="calc-input" placeholder="Contoh: 3*3 + 4*4" style="margin: 0; font-size: 0.85rem; padding: 8px;">
            <button type="button" class="btn" style="width: auto; padding: 8px 12px; font-size: 0.85rem;" onclick="hitungCepat()">Hitung</button>
            <input type="text" id="calc-hasil" readonly placeholder="Hasil" style="margin: 0; width: 90px; font-weight: 700; text-align: center; background: var(--card-bg); padding: 8px; font-size: 0.85rem;">
        </div>
    </div>
</div>

<div id="modal-konfirmasi-kirim" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(15,23,42,0.6); backdrop-filter:blur(3px); z-index:9999; align-items:center; justify-content:center;">
    <div style="background:var(--card-bg); border:2px solid var(--border-color); padding:30px; border-radius:16px; width:90%; max-width:420px; box-shadow:var(--shadow); text-align:center;">
        <div style="font-size:3rem; margin-bottom:10px;">&#9888;</div>
        <h3 style="margin-bottom:10px;">Konfirmasi Pengiriman LKM</h3>
        <p style="font-size:0.9rem; color:var(--text-muted); margin-bottom:20px;">Apakah Anda yakin ingin mengirimkan jawaban pertemuan ini?</p>
        <div style="display:flex; gap:10px;">
            <button type="button" onclick="tutupKonfirmasiKirim()" class="btn btn-secondary" style="flex:1;">Periksa Lagi</button>
            <button type="button" onclick="eksekusiKirimUjian()" class="btn btn-success" style="flex:1;">Ya, Kirim Sekarang</button>
        </div>
    </div>
</div>

<div style="background: var(--card-bg); padding: 25px; border-radius: 14px; border: 2px solid var(--border-color); text-align: left;">
    <p style="color: #10b981; font-weight: bold;">Status: Pengerjaan ''' + pertemuan.nama_pertemuan + ''' (Auto-save Aktif)</p>
    <form id="form-ujian" method="POST" enctype="multipart/form-data">
        <input type="hidden" name="jumlah_kecurangan" id="input-kecurangan" value="0">
        <input type="hidden" name="durasi_kecurangan" id="input-durasi-kecurangan" value="0">
        ''' + form_soal_html + '''
        <label style="margin-top: 15px; display:block;"><b>Unggah Foto Pendukung Keseluruhan (Opsional):</b></label>
        <input type="file" name="foto" accept="image/*" style="background: var(--card-bg); padding: 12px; margin-bottom: 25px;">
        <button type="button" class="btn btn-success" onclick="bukaKonfirmasiKirim()" style="padding: 16px; font-size: 1.05rem;">Kirim Jawaban ''' + pertemuan.nama_pertemuan + '''</button>
    </form>
</div>

<script>
let activeTa = null;
function setTarget(el) { activeTa = el; }
function bukaModalSimbolSiswa() { document.getElementById('modal-simbol-siswa').style.display = 'flex'; }
function tutupModalSimbolSiswa() { document.getElementById('modal-simbol-siswa').style.display = 'none'; }
function pilihSimbolSiswa(sym) {
    if(!activeTa) { const tas = document.querySelectorAll('textarea'); if(tas.length > 0) activeTa = tas[0]; }
    if(activeTa) {
        const start = activeTa.selectionStart, end = activeTa.selectionEnd, val = activeTa.value;
        activeTa.value = val.substring(0, start) + sym + val.substring(end);
        activeTa.selectionStart = activeTa.selectionEnd = start + sym.length;
        activeTa.focus();
        simpanDraft();
    }
    tutupModalSimbolSiswa();
}
function bukaKonfirmasiKirim() { document.getElementById('modal-konfirmasi-kirim').style.display = 'flex'; }
function tutupKonfirmasiKirim() { document.getElementById('modal-konfirmasi-kirim').style.display = 'none'; }
function eksekusiKirimUjian() {
    tutupKonfirmasiKirim();
    if (waktuMulaiKeluar !== null) { totalDurasiKeluar += Math.floor((Date.now() - waktuMulaiKeluar) / 1000); document.getElementById('input-durasi-kecurangan').value = totalDurasiKeluar; }
    localStorage.removeItem(draftKey);
    showLoading('Mengirimkan jawaban...');
    document.getElementById('form-ujian').submit();
}
const draftKey = "draft_lkm_''' + str(id_p) + '''";
function simpanDraft() {
    const tas = document.querySelectorAll('textarea');
    let dataDraft = {};
    tas.forEach((ta, i) => { dataDraft[i] = ta.value; });
    localStorage.setItem(draftKey, JSON.stringify(dataDraft));
}
document.addEventListener('DOMContentLoaded', () => {
    const tas = document.querySelectorAll('textarea');
    if(tas.length > 0) activeTa = tas[0];
    const saved = localStorage.getItem(draftKey);
    if(saved) {
        try {
            const dataDraft = JSON.parse(saved);
            tas.forEach((ta, i) => { if(dataDraft[i] !== undefined) { ta.value = dataDraft[i]; cekTerisi(i); } });
        } catch(e) {}
    }
});
function hitungCepat() {
    try {
        let inputVal = document.getElementById('calc-input').value;
        let cleaned = inputVal.replace(/[\\u00D7]/g, '*').replace(/[\\u00F7]/g, '/');
        const res = eval(cleaned);
        document.getElementById('calc-hasil').value = res;
    } catch(e) { document.getElementById('calc-hasil').value = "Error"; }
}
function lompatKeSoal(idx) { document.getElementById('card-soal-' + idx).scrollIntoView({ behavior: 'smooth', block: 'center' }); }
function cekTerisi(idx) {
    const val = document.getElementById('jawaban_' + idx).value.trim(), btn = document.getElementById('palet-btn-' + idx);
    if(val.length > 0) { btn.style.background = 'var(--success)'; btn.style.color = 'white'; btn.style.borderColor = 'var(--success)'; }
    else { btn.style.background = 'var(--card-bg)'; btn.style.color = 'var(--text-main)'; btn.style.borderColor = 'var(--border-color)'; }
}
let kecuranganCount = 0, totalDurasiKeluar = 0, waktuMulaiKeluar = null;
document.addEventListener("visibilitychange", () => {
    if (document.hidden) { kecuranganCount++; waktuMulaiKeluar = Date.now(); document.getElementById('input-kecurangan').value = kecuranganCount; showToast("Peringatan: Anda meninggalkan halaman ujian!", true); }
    else if (waktuMulaiKeluar !== null) { totalDurasiKeluar += Math.floor((Date.now() - waktuMulaiKeluar) / 1000); waktuMulaiKeluar = null; document.getElementById('input-durasi-kecurangan').value = totalDurasiKeluar; }
});
</script>
</div></body></html>'''
    )

@app.route('/siswa/riwayat')
@login_required
def siswa_riwayat():
    if current_user.role != 'siswa':
        return 'Akses ditolak!'
    user_identifier = current_user.nama or current_user.username
    riwayat_tugas = JawabanSiswa.query.filter_by(nama_siswa=user_identifier).all()
    html_riwayat = ''
    for t in riwayat_tugas:
        tampilan_foto = f'<br><a href="/static/uploads/{t.foto}" target="_blank"><img src="/static/uploads/{t.foto}" width="100" style="margin-top:8px; border:2px solid var(--border-color); border-radius:8px;" /></a>' if t.foto else ''
        info_kecurangan = f'<br><span style="color:#e11d48; font-size:0.8rem;">&#9888; Keluar tab: {t.jumlah_kecurangan} kali (Durasi: {t.durasi_kecurangan_str})</span>' if t.jumlah_kecurangan and t.jumlah_kecurangan > 0 else ''
        tampil_nilai = f"<b>{t.nilai_angka}</b>" if t.nilai_angka is not None else "Belum Dinilai"
        html_riwayat += f"""
        <tr>
            <td style="font-weight: 700;">{t.tugas}</td>
            <td>{t.jawaban or "-"}{tampilan_foto}{info_kecurangan}</td>
            <td>
                <div style="font-weight: 800; color: #10b981; margin-bottom: 6px;">Nilai: {tampil_nilai}</div>
                <div style="background: var(--bg-main); padding: 12px; border-radius: 8px; border: 1px solid var(--border-color); font-size: 0.9rem;">{t.evaluasi_ai or "-"}</div>
            </td>
        </tr>
        """
    if not html_riwayat:
        html_riwayat = '<tr><td colspan="3"><div class="empty-state" style="margin:0;"><div class="empty-state-icon">&#128202;</div><div class="empty-state-text">Belum ada riwayat tugas atau ujian yang dikirim.</div><a href="/siswa/pilih-ujian" class="btn btn-success" style="display:inline-flex; width:auto; padding:10px 20px; font-size:0.9rem;">Mulai Kerjakan Tugas Sekarang</a></div></td></tr>'

    return '<!DOCTYPE html><html lang="id"><head><title>Riwayat Tugas</title>' + BASE_STYLE + """</head><body><div id="toast-container"></div>{navbar}<div class="box" style="max-width: 1000px;"><div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px; flex-wrap:wrap; gap:10px;"><h2>&#128202; Riwayat & Nilai Tugas</h2><a href="/siswa/cetak-rapor" target="_blank" class="btn btn-success" style="padding: 10px 16px; width:auto;">&#128424;&#65039; Cetak Transkrip / Rapor PDF</a></div><p>Daftar tugas, jawaban, serta hasil evaluasi dan penilaian:</p><div class="table-container"><table><tr><th>Tugas</th><th>Jawaban & Lampiran Foto</th><th>Nilai & Evaluasi AI / Guru</th></tr>{html_riwayat_tabel}</table></div></div></body></html>""".replace('{navbar}', render_navbar()).replace('{html_riwayat_tabel}', html_riwayat)

@app.route('/siswa/cetak-rapor')
@login_required
def cetak_rapor():
    if current_user.role != 'siswa':
        return 'Akses ditolak!'
    user_name = current_user.nama or current_user.username
    riwayat = JawabanSiswa.query.filter_by(nama_siswa=user_name).all()
    
    tabel_html = ''
    total_nilai = 0
    jumlah_dinilai = 0
    for idx, r in enumerate(riwayat, 1):
        n_str = str(r.nilai_angka) if r.nilai_angka is not None else 'Belum Dinilai'
        if r.nilai_angka is not None:
            total_nilai += r.nilai_angka
            jumlah_dinilai += 1
        tabel_html += f"""
        <tr>
            <td style="text-align:center;">{idx}</td>
            <td style="font-weight:700;">{r.tugas}</td>
            <td style="text-align:center; font-weight:800; color:#047857;">{n_str}</td>
            <td>{r.evaluasi_ai or 'Belum ada catatan'}</td>
        </tr>
        """
        
    rata_rata = round(total_nilai / jumlah_dinilai, 2) if jumlah_dinilai > 0 else 0
    waktu_cetak = datetime.now().strftime('%d %B %Y, %H:%M')
    
    return f"""
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <title>Transkrip Nilai - {user_name}</title>
        <style>
            body {{ font-family: 'Times New Roman', Times, serif; color: #000; margin: 40px; background: #fff; }}
            .header {{ text-align: center; border-bottom: 3px double #000; padding-bottom: 15px; margin-bottom: 25px; }}
            .header h2, .header h3, .header p {{ margin: 4px 0; }}
            .info-table {{ width: 100%; margin-bottom: 20px; font-size: 1.05rem; }}
            .info-table td {{ padding: 4px 0; }}
            table.rapor {{ width: 100%; border-collapse: collapse; margin-top: 15px; margin-bottom: 25px; }}
            table.rapor th, table.rapor td {{ border: 1px solid #000; padding: 10px; font-size: 0.95rem; text-align: left; vertical-align: top; }}
            table.rapor th {{ background: #f2f2f2; text-align: center; }}
            .summary {{ font-weight: bold; font-size: 1.05rem; margin-bottom: 40px; }}
            .footer-sign {{ float: right; text-align: center; margin-top: 30px; width: 250px; }}
            .footer-sign .space {{ height: 70px; }}
            @media print {{
                .no-print {{ display: none; }}
                body {{ margin: 10px; }}
            }}
        </style>
    </head>
    <body onload="window.print()">
        <div class="no-print" style="background:#e0e7ff; color:#3730a3; padding:12px; border-radius:8px; margin-bottom:20px; text-align:center; font-family:'Plus Jakarta Sans', sans-serif; font-weight:700;">
            Halaman cetak otomatis dibuka.<br><br>
            <button onclick="window.print()" style="background:#4f46e5; color:white; border:none; padding:10px 20px; border-radius:8px; cursor:pointer; font-weight:bold;">Cetak / Simpan PDF</button>
            <a href="/siswa/riwayat" style="margin-left:15px; color:#4f46e5;">&larr; Kembali ke Riwayat</a>
        </div>
        <div class="header">
            <h3>PORTAL AKADEMIK SEKOLAH MENENGAH</h3>
            <h2>TRANSKRIP NILAI & EVALUASI BELAJAR SISWA</h2>
            <p style="font-size: 0.9rem; font-style: italic;">Laporan Resmi Hasil Pengerjaan Tugas, LKM, dan Ujian Evaluasi</p>
        </div>
        <table class="info-table">
            <tr>
                <td style="width: 150px;"><b>Nama Siswa</b></td>
                <td style="width: 20px;">:</td>
                <td><b>{user_name}</b></td>
                <td style="width: 150px;"><b>Tanggal Cetak</b></td>
                <td style="width: 20px;">:</td>
                <td>{waktu_cetak}</td>
            </tr>
            <tr>
                <td><b>Status Akun</b></td>
                <td>:</td>
                <td>Siswa Aktif</td>
                <td><b>Kurikulum</b></td>
                <td>:</td>
                <td>Teori Belajar & Evaluasi AI</td>
            </tr>
        </table>
        <table class="rapor">
            <thead>
                <tr>
                    <th style="width: 40px;">No</th>
                    <th style="width: 200px;">Mata / Modul Tugas</th>
                    <th style="width: 90px;">Nilai Angka</th>
                    <th>Ulasan & Evaluasi Pembelajaran (AI / Guru)</th>
                </tr>
            </thead>
            <tbody>
                {tabel_html if tabel_html else '<tr><td colspan="4" style="text-align:center; font-style:italic;">Belum ada data tugas atau ujian tercatat.</td></tr>'}
            </tbody>
        </table>
        <div class="summary">
            Rata-rata Nilai Keseluruhan: <span style="color:#047857; text-decoration: underline;">{rata_rata}</span>
        </div>
        <div class="footer-sign">
            <p>Mengetahui,</p>
            <p><b>Wali Kelas / Guru Pengampu</b></p>
            <div class="space"></div>
            <p><b>( Tim Akademik Sekolah )</b></p>
        </div>
    </body>
    </html>
    """

@app.route('/guru/ekspor-excel')
@login_required
def guru_ekspor_excel():
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    si = io.StringIO()
    cw = csv.writer(si, delimiter=';')
    cw.writerow(['No', 'Nama Siswa', 'Tugas / Modul', 'Jumlah Keluar Tab', 'Durasi Keluar Tab', 'Nilai Akhir'])
    semua_j = JawabanSiswa.query.all()
    for idx, d in enumerate(semua_j, 1):
        nilai_eks = d.nilai_angka if d.nilai_angka is not None else 'Belum Dinilai'
        cw.writerow([idx, d.nama_siswa, d.tugas, d.jumlah_kecurangan or 0, d.durasi_kecurangan_str or '0 detik', nilai_eks])
    return Response(
        si.getvalue().encode('utf-8-sig'),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment;filename=rekap_nilai_siswa.csv'}
    )

@app.route('/guru/laporan')
@login_required
def guru_laporan():
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    semua_j = JawabanSiswa.query.all()
    data_valid = []
    for d in semua_j:
        if d.nilai_angka is not None:
            data_valid.append({'nama': d.nama_siswa, 'nilai': d.nilai_angka})
            
    total = len(data_valid)
    rata_rata = round(sum(item['nilai'] for item in data_valid) / total, 1) if total > 0 else 0
    nama_list = [item['nama'] for item in data_valid]
    nilai_list = [item['nilai'] for item in data_valid]
    
    return '<!DOCTYPE html><html lang="id"><head><title>Laporan & Analitik</title>' + BASE_STYLE + """</head><body><div id="toast-container"></div>{navbar}<div class="box" style="max-width: 900px;"><h2 style="margin-bottom:20px;">Laporan & Analitik Performa Kelas</h2>
    <div style="display: flex; gap: 20px; margin-bottom: 30px; flex-wrap: wrap;">
        <div style="flex: 1; background: #ecfdf5; border: 2px solid #a7f3d0; padding: 20px; border-radius: 14px; text-align: center;">
            <span style="color: #065f46; font-weight: 700;">Total Tugas Dinilai</span>
            <div style="font-size: 2.5rem; font-weight: 800; color: #059669; margin-top: 5px;">{total}</div>
        </div>
        <div style="flex: 1; background: #fffbeb; border: 2px solid #fde68a; padding: 20px; border-radius: 14px; text-align: center;">
            <span style="color: #92400e; font-weight: 700;">Rata-rata Nilai Kelas</span>
            <div style="font-size: 2.5rem; font-weight: 800; color: #d97706; margin-top: 5px;">{rata_rata}</div>
        </div>
    </div>
    <div style="background: var(--card-bg); padding: 20px; border-radius: 14px; border: 2px solid var(--border-color);">
        <canvas id="grafikKelas" style="max-height: 350px;"></canvas>
    </div>
    <script>
    new Chart(document.getElementById('grafikKelas'), {
        type: 'bar',
        data: {
            labels: {nama_list},
            datasets: [{
                label: 'Nilai Siswa',
                data: {nilai_list},
                backgroundColor: 'rgba(99, 102, 241, 0.85)',
                borderColor: '#6366f1',
                borderWidth: 2,
                borderRadius: 8
            }]
        },
        options: {
            responsive: true,
            scales: {
                y: { max: 100, beginAtZero: true }
            }
        }
    });
    </script></div></body></html>""".replace('{navbar}', render_navbar()).replace('{total}', str(total)).replace('{rata_rata}', str(rata_rata)).replace('{nama_list}', str(nama_list)).replace('{nilai_list}', str(nilai_list))

@app.route('/guru/pengaturan-ujian', methods=['GET', 'POST'])
@login_required
def pengaturan_ujian():
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    ujian = PengaturanUjian.query.filter_by(nama_ujian='Ujian Evaluasi').first()
    if request.method == 'POST':
        ujian.status = request.form.get('status')
        ujian.waktu_mulai = request.form.get('waktu_mulai')
        ujian.waktu_selesai = request.form.get('waktu_selesai')
        ujian.durasi_menit = int(request.form.get('durasi_menit', 0))
        ujian.max_percobaan = int(request.form.get('max_percobaan', 0))
        db.session.commit()
        return redirect(url_for('pengaturan_ujian'))
    return '<!DOCTYPE html><html lang="id"><head><title>Pengaturan Ujian</title>' + BASE_STYLE + """</head><body><div id="toast-container"></div>{navbar}<div class="box" style="max-width: 600px;"><h2>&#9881;&#65039; Pengaturan Waktu & Batasan Ujian</h2><form method="POST" onsubmit="showLoading('Menyimpan pengaturan...')"><label>Status Ujian:</label><select name="status"><option value="buka_selalu" {sel_buka}>Dibuka</option><option value="jadwal" {sel_jadwal}>Jadwal Tertentu</option><option value="tutup" {sel_tutup}>Ditutup</option></select><label>Durasi Ujian (Menit):</label><input type="number" name="durasi_menit" value="{durasi}"><label>Batas Maksimal Percobaan Siswa (0 = Tanpa Batas):</label><input type="number" name="max_percobaan" value="{max_p}"><button type="submit" class="btn btn-success" style="margin-top:15px;">Simpan Pengaturan</button></form></div></body></html>""".replace('{navbar}', render_navbar()).replace('{sel_buka}', 'selected' if ujian.status == 'buka_selalu' else '').replace('{sel_jadwal}', 'selected' if ujian.status == 'jadwal' else '').replace('{sel_tutup}', 'selected' if ujian.status == 'tutup' else '').replace('{durasi}', str(ujian.durasi_menit)).replace('{max_p}', str(ujian.max_percobaan))

@app.route('/guru/koreksi')
@login_required
def koreksi_siswa():
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    
    daftar_pertemuan = PertemuanLKM.query.all()
    html_pertemuan = ''
    for p in daftar_pertemuan:
        html_pertemuan += f"""
        <a href="/guru/koreksi/pilih-siswa?tugas=LKM - {p.nama_pertemuan}" class="box" style="margin:0; text-decoration:none; display:block; border: 2px solid var(--border-color);">
            <h3 style="margin:0 0 5px 0;">&#128218; LKM - {p.nama_pertemuan}</h3>
            <p style="margin:0; font-size:0.85rem;">Klik untuk pilih siswa & koreksi</p>
        </a>
        """
    if not html_pertemuan:
        html_pertemuan = '<div class="empty-state" style="grid-column: 1/-1;"><div class="empty-state-icon">&#128218;</div><div class="empty-state-text">Belum ada pertemuan LKM yang tersedia.</div></div>'

    return '<!DOCTYPE html><html lang="id"><head><title>Koreksi Siswa</title>' + BASE_STYLE + f"""</head><body><div id="toast-container"></div>{render_navbar()}<div class="box" style="max-width: 950px;"><h2>&#128221; Panel Koreksi Guru - Pilih Kategori Tugas</h2><p style="margin-bottom:25px;">Silakan pilih jenis modul atau pertemuan tugas yang ingin dikoreksi:</p>

<h3 style="margin-bottom:15px; border-bottom:2px solid var(--border-color); padding-bottom:8px;">1. Lembar Kerja Murid (LKM) Berdasarkan Pertemuan</h3>
<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 15px; margin-bottom: 35px;">
    {html_pertemuan}
</div>

<h3 style="margin-bottom:15px; border-bottom:2px solid var(--border-color); padding-bottom:8px;">2. Ujian & Latihan Mandiri</h3>
<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 15px;">
    <a href="/guru/koreksi/pilih-siswa?tugas=Soal Latihan Mandiri" class="box" style="margin:0; text-decoration:none; display:block; border: 2px solid var(--border-color); background:rgba(59,130,246,0.03);">
        <h3 style="margin:0 0 5px 0; color:#2563eb;">&#128221; Soal Latihan Mandiri</h3>
        <p style="margin:0; font-size:0.85rem;">Koreksi hasil latihan mandiri siswa</p>
    </a>
    <a href="/guru/koreksi/pilih-siswa?tugas=Ujian Evaluasi" class="box" style="margin:0; text-decoration:none; display:block; border: 2px solid var(--border-color); background:rgba(239,68,68,0.03);">
        <h3 style="margin:0 0 5px 0; color:#dc2626;">&#9888; Ujian Evaluasi Resmi</h3>
        <p style="margin:0; font-size:0.85rem;">Koreksi hasil ujian evaluasi akhir</p>
    </a>
</div>

</div></body></html>"""

@app.route('/guru/koreksi/pilih-siswa')
@login_required
def koreksi_pilih_siswa():
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    tugas_target = request.args.get('tugas')
    if not tugas_target:
        return redirect(url_for('koreksi_siswa'))
    
    daftar_pengumpulan = JawabanSiswa.query.filter_by(tugas=tugas_target).all()
    html_siswa = ''
    for j in daftar_pengumpulan:
        status_nilai = f"Nilai: <b>{j.nilai_angka}</b>" if j.nilai_angka is not None else '<span style="color:#f59e0b;">Belum Dinilai</span>'
        html_siswa += f"""
        <div style="background:var(--bg-main); border:2px solid var(--border-color); padding:20px; border-radius:14px; display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <div>
                <h3 style="margin:0 0 4px 0;">&#128100; {j.nama_siswa}</h3>
                <p style="margin:0; font-size:0.85rem;">Status: {status_nilai} | Keluar Tab: {j.jumlah_kecurangan or 0}x</p>
            </div>
            <a href="/guru/koreksi/detail/{j.id}" class="btn" style="width:auto; padding:10px 20px;">Buka & Koreksi</a>
        </div>
        """
    if not html_siswa:
        html_siswa = f'<div class="empty-state"><div class="empty-state-icon">&#128221;</div><div class="empty-state-text">Belum ada siswa yang mengumpulkan tugas <b>{tugas_target}</b>.</div></div>'

    return f"""
    <!DOCTYPE html><html lang="id"><head><title>Pilih Siswa</title>{BASE_STYLE}</head>
    <body>{render_navbar()}<div id="toast-container"></div>
    <div class="box" style="max-width: 850px;">
        <a href="/guru/koreksi" style="font-size:0.9rem; display:inline-block; margin-bottom:15px;">&larr; Kembali ke Pilih Kategori</a>
        <h2>Pilih Siswa: {tugas_target}</h2>
        <p style="margin-bottom:20px;">Berikut adalah daftar siswa yang sudah mengumpulkan tugas ini:</p>
        {html_siswa}
    </div></body></html>
    """

@app.route('/guru/koreksi/detail/<int:id_jawaban>', methods=['GET', 'POST'])
@login_required
def koreksi_detail_siswa(id_jawaban):
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    
    j_item = db.get_or_404(JawabanSiswa, id_jawaban)
    
    if request.method == 'POST':
        try:
            input_nilai = request.form.get('nilai', '0').strip()
            j_item.nilai_angka = float(input_nilai)
            
            # Simpan umpan balik guru manual
            input_feedback = request.form.get('feedback_guru', '').strip()
            if input_feedback:
                # Gabungkan atau perbarui ulasan evaluasi dengan catatan guru
                j_item.evaluasi_ai = f"<strong>Catatan / Umpan Balik Guru:</strong><br>{input_feedback}<br><br><strong>Analisis AI:</strong><br>{j_item.evaluasi_ai}"
            
            db.session.commit()
            return f'<script>alert("Nilai dan umpan balik berhasil disimpan!");window.location="/guru/koreksi/detail/{id_jawaban}";</script>'
        except ValueError:
            pass

    daftar_soal_info = []
    if "LKM -" in j_item.tugas:
        nama_p_target = j_item.tugas.replace("LKM - ", "")
        p_obj = PertemuanLKM.query.filter_by(nama_pertemuan=nama_p_target).first()
        if p_obj:
            soals_db = SoalLKM.query.filter_by(pertemuan_id=p_obj.id).all()
            for s in soals_db:
                daftar_soal_info.append({'pertanyaan': s.pertanyaan, 'kunci': s.kunci_jawaban})
    elif "Latihan" in j_item.tugas:
        soals_db = SoalLain.query.filter_by(kategori='latihan').all()
        for s in soals_db:
            daftar_soal_info.append({'pertanyaan': s.pertanyaan, 'kunci': s.kunci_jawaban})
    elif "Ujian Evaluasi" in j_item.tugas:
        soals_db = SoalLain.query.filter_by(kategori='evaluasi').all()
        for s in soals_db:
            daftar_soal_info.append({'pertanyaan': s.pertanyaan, 'kunci': s.kunci_jawaban})

    rincian_jawaban_html = ""
    if j_item.jawaban:
        baris_jawaban = j_item.jawaban.split("-------------------")
        for idx, item_j in enumerate(baris_jawaban, 1):
            kunci_resmi = daftar_soal_info[idx-1]['kunci'] if (idx-1 < len(daftar_soal_info)) else 'Kunci jawaban tidak tersedia'
            tanya_resmi = daftar_soal_info[idx-1]['pertanyaan'] if (idx-1 < len(daftar_soal_info)) else f'Pertanyaan Soal {idx}'
            
            rincian_jawaban_html += f"""
            <div style="background:var(--bg-main); border:2px solid var(--border-color); padding:20px; border-radius:14px; margin-bottom:15px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <span style="background:var(--primary); color:white; padding:4px 10px; border-radius:8px; font-size:0.8rem; font-weight:800;">Soal No. {idx}</span>
                    <div style="display:flex; align-items:center; gap:8px;">
                        <label style="font-size:0.85rem; font-weight:700; margin:0;">Nilai Soal Ini:</label>
                        <input type="number" step="0.1" id="nilai_soal_{idx}" class="input-nilai-soal" oninput="hitungTotalNilaiOtomatis()" placeholder="0" style="width:80px; margin:0; padding:8px; text-align:center; font-weight:bold;">
                    </div>
                </div>
                <p style="font-size:1.05rem; font-weight:700; color:var(--text-main); margin-top:10px; white-space:pre-line;">{tanya_resmi}</p>
                
                <div style="background:var(--card-bg); border:2px solid var(--border-color); padding:14px; border-radius:10px; margin-top:10px;">
                    &#128100; <b>Jawaban Siswa:</b><br>
                    <p style="margin:5px 0 0 0; white-space:pre-line; color:var(--text-main);">{item_j.strip()}</p>
                </div>
                
                <div style="background:#ecfdf5; border:1px solid #a7f3d0; color:#065f46; padding:12px; border-radius:10px; margin-top:10px; font-size:0.9rem;">
                    &#128273; <b>Kunci Jawaban Resmi Guru:</b><br>{kunci_resmi}
                </div>
            </div>
            """
    else:
        rincian_jawaban_html = '<p>Tidak ada rincian jawaban tersimpan.</p>'

    tampilan_foto = f'<div style="margin-top:20px;"><label><b>Lampiran Foto Siswa:</b></label><br><a href="/static/uploads/{j_item.foto}" target="_blank"><img src="/static/uploads/{j_item.foto}" width="300" style="margin-top:8px; border:2px solid var(--border-color); border-radius:10px;" /></a></div>' if j_item.foto else ''
    nilai_sekarang = j_item.nilai_angka if j_item.nilai_angka is not None else ''

    return render_template_string(
        '<!DOCTYPE html><html lang="id"><head><title>Koreksi Jawaban</title>' + BASE_STYLE + '''</head>
        <body>''' + render_navbar() + '''<div id="toast-container"></div>
        <div class="box" style="max-width: 950px;">
            <a href="/guru/koreksi/pilih-siswa?tugas=''' + j_item.tugas + '''" style="font-size:0.9rem; display:inline-block; margin-bottom:15px;">&larr; Kembali ke Daftar Siswa</a>
            <h2>Koreksi Detail: ''' + j_item.nama_siswa + '''</h2>
            <p style="margin-bottom:20px;">Tugas: <b>''' + j_item.tugas + '''</b> | Pelanggaran Keluar Tab: <b>''' + str(j_item.jumlah_kecurangan or 0) + ''' kali (''' + str(j_item.durasi_kecurangan_str) + ''')</b></p>
            
            <div style="background:var(--card-bg); border:2px solid var(--border-color); padding:25px; border-radius:16px; margin-bottom:25px;">
                <h3>&#129302; Analisis AI Komprehensif (Semua Soal Sekaligus)</h3>
                <div style="background:var(--bg-main); border:1px solid var(--border-color); padding:15px; border-radius:12px; margin-top:10px; font-size:0.95rem; line-height:1.6;">
                    ''' + (j_item.evaluasi_ai or 'Belum dianalisis oleh AI.') + '''
                </div>
                <a href="/guru/ai-koreksi-detail/''' + str(j_item.id) + '''" class="btn btn-warning" style="margin-top:15px; width:auto;" onclick="showLoading('Gemini AI sedang menganalisis seluruh jawaban secara mendalam...')">&#129302; Jalankan / Perbarui Analisis AI Komprehensif</a>
            </div>

            <h3 style="margin-bottom:15px; border-bottom:2px solid var(--border-color); padding-bottom:8px;">Rincian Jawaban & Penilaian Per Soal</h3>
            ''' + rincian_jawaban_html + '''
            ''' + tampilan_foto + '''

            <hr style="margin:30px 0; border:0; border-top:1px solid var(--border-color);">
            <div style="background:var(--card-bg); border:2px solid var(--border-color); padding:25px; border-radius:16px;">
                <h3>Rekap Nilai & Umpan Balik Guru</h3>
                <p style="font-size:0.85rem; color:var(--text-muted); margin-bottom:15px;">Masukkan nilai total angka dan berikan catatan/umpan balik manual yang akan langsung tampil pada riwayat siswa (contoh: "belajar lagi dek").</p>
                <form method="POST" onsubmit="showLoading('Menyimpan penilaian...')">
                    <label>Total Nilai Angka Akhir:</label>
                    <input type="number" step="0.1" name="nilai" id="input-total-nilai" value="''' + str(nilai_sekarang) + '''" required placeholder="Contoh: 85" style="max-width:200px;">
                    
                    <label style="margin-top:10px; display:block;">Umpan Balik / Catatan Manual untuk Siswa:</label>
                    <textarea name="feedback_guru" placeholder="Tuliskan umpan balik atau catatan khusus (contoh: Belajar lagi dek, tingkatkan ketelitianmu!)..." style="height:100px;"></textarea>
                    
                    <button type="submit" class="btn btn-success" style="width:auto; padding:12px 24px; margin-top:10px;">Simpan Nilai & Umpan Balik</button>
                </form>
            </div>
        </div>

        <script>
        function hitungTotalNilaiOtomatis() {
            const inputs = document.querySelectorAll('.input-nilai-soal');
            let total = 0;
            let adaIsi = false;
            inputs.forEach(inp => {
                const val = parseFloat(inp.value);
                if(!isNaN(val)) {
                    total += val;
                    adaIsi = true;
                }
            });
            if(adaIsi) {
                document.getElementById('input-total-nilai').value = Math.round(total * 10) / 10;
            }
        }
        </script>
        </body></html>'''
    )

@app.route('/guru/ai-koreksi-detail/<int:id_jawaban>')
@login_required
def ai_koreksi_detail(id_jawaban):
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    
    if not ai_client:
        return f'<script>alert("Kunci API Gemini belum dikonfigurasi!");window.location="/guru/koreksi/detail/{id_jawaban}";</script>'

    item = db.get_or_404(JawabanSiswa, id_jawaban)
    daftar_soal_teks = ""
    golongan_terdeteksi = set()
    
    if "LKM -" in item.tugas:
        nama_p_target = item.tugas.replace("LKM - ", "")
        p_obj = PertemuanLKM.query.filter_by(nama_pertemuan=nama_p_target).first()
        if p_obj:
            soal_lkm_list = SoalLKM.query.filter_by(pertemuan_id=p_obj.id).all()
            ref_list = []
            for s in soal_lkm_list:
                gol_nama = GOLONGAN_LKM_CONFIG.get(str(s.golongan), {}).get('nama', f'Golongan {s.golongan}')
                golongan_terdeteksi.add(gol_nama)
                ref_list.append(f"[{gol_nama}] Pertanyaan: {s.pertanyaan} | Kunci Jawaban Resmi: {s.kunci_jawaban}")
            daftar_soal_teks = "\n".join(ref_list)
    elif "Latihan" in item.tugas:
        soal_lain_list = SoalLain.query.filter_by(kategori='latihan').all()
        daftar_soal_teks = "\n".join([f"Pertanyaan: {s.pertanyaan} | Kunci Jawaban Resmi: {s.kunci_jawaban}" for s in soal_lain_list])
    else:
        soal_lain_list = SoalLain.query.filter_by(kategori='evaluasi').all()
        daftar_soal_teks = "\n".join([f"Pertanyaan: {s.pertanyaan} | Kunci Jawaban Resmi: {s.kunci_jawaban}" for s in soal_lain_list])

    daftar_golongan_teks = ", ".join(list(golongan_terdeteksi)) if golongan_terdeteksi else "Umum"

    prompt = f"""
    Bertindaklah sebagai seorang guru ahli dan objektif. Analisis seluruh rangkaian jawaban siswa untuk seluruh soal berikut sekaligus dalam satu ulasan komprehensif.
    
    Nama Siswa: {item.nama_siswa}
    Tugas / Modul: {item.tugas}
    Golongan Soal: {daftar_golongan_teks}
    
    Daftar Pertanyaan Lengkap Beserta Kunci Jawabannya:
    {daftar_soal_teks}
    
    Jawaban Keseluruhan dari Siswa:
    {item.jawaban}
    
    Instruksi:
    Evaluasi seluruh soal secara rinci dan terstruktur. 
    Format Output dalam HTML bersih (<p>, <ul>, <li>, <strong>):
    1. **Ulasan Umum Performa**: Komentar menyeluruh terhadap pemahaman siswa pada tugas ini.
    2. **Koreksi Per Nomor / Golongan**: Ulasan langsung apakah jawaban siswa untuk setiap nomor sudah sesuai dengan kunci jawaban resmi.
    Jangan berikan rekomendasi angka nilai, cukup berikan ulasan analitis akademis secara mendalam dan menyeluruh untuk semua soal sekaligus.
    """

    try:
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        item.evaluasi_ai = response.text
        db.session.commit()
    except Exception as e:
        item.evaluasi_ai = f"<p style='color:red;'>Gagal menganalisis: {str(e)}</p>"
        db.session.commit()

    return redirect(url_for('koreksi_detail_siswa', id_jawaban=id_jawaban))

@app.route('/guru/beri-nilai/<int:id_jawaban>', methods=['POST'])
@login_required
def beri_nilai(id_jawaban):
    if current_user.role != 'guru':
        return 'Akses ditolak!'
    jawaban_terpilih = db.get_or_404(JawabanSiswa, id_jawaban)
    try:
        input_nilai = request.form.get('nilai', '0').strip()
        jawaban_terpilih.nilai_angka = float(input_nilai)
        db.session.commit()
    except ValueError:
        pass
    return redirect(url_for('koreksi_detail_siswa', id_jawaban=id_jawaban))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)