from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, FloatField, TextAreaField, DateField, SelectField, FileField, MultipleFileField
from wtforms.validators import DataRequired, Optional, NumberRange
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from flask_mail import Mail, Message
from datetime import datetime
import os
import csv
import io
import base64
from werkzeug.utils import secure_filename
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

# Configuration de l'application
app = Flask(__name__)
app.config['SECRET_KEY'] = 'gasa_formation_2025_secret_key_very_secure'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///memoires.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max pour plusieurs fichiers

# Configuration Email (optionnelle - à adapter si tu veux utiliser les emails)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = ''  # Laisse vide si pas utilisé
app.config['MAIL_PASSWORD'] = ''  # Laisse vide si pas utilisé
app.config['MAIL_DEFAULT_SENDER'] = 'noreply@gasaformation.com'

# Créer les dossiers nécessaires
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('static', exist_ok=True)
os.makedirs('templates', exist_ok=True)

# Initialisation des extensions
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Veuillez vous connecter pour accéder à cette page'
mail = Mail(app)

# ==================== MODÈLES DE DONNÉES ====================

class User(UserMixin):
    """Modèle utilisateur pour l'authentification"""
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash
    
    @staticmethod
    def get(user_id):
        users = {
            '1': User('1', 'admin', 'admin123'),
            '2': User('2', 'gasa', 'gasa2025')
        }
        return users.get(user_id)
    
    @staticmethod
    def find_by_username(username):
        users = {
            'admin': User.get('1'),
            'gasa': User.get('2')
        }
        return users.get(username)
    
    def check_password(self, password):
        return password == self.password_hash

class Document(db.Model):
    """Modèle pour les fichiers multiples"""
    id = db.Column(db.Integer, primary_key=True)
    memoire_id = db.Column(db.Integer, db.ForeignKey('memoire.id'), nullable=False)
    nom_fichier = db.Column(db.String(200), nullable=False)
    type_fichier = db.Column(db.String(50), nullable=False, default='annexe')
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    memoire = db.relationship('Memoire', backref=db.backref('documents', lazy=True, cascade='all, delete-orphan'))

class Memoire(db.Model):
    """Modèle principal des mémoires"""
    id = db.Column(db.Integer, primary_key=True)
    titre = db.Column(db.String(200), nullable=False)
    auteur = db.Column(db.String(100), nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    filiere = db.Column(db.String(100), nullable=False)
    directeur = db.Column(db.String(100), nullable=False)
    mention = db.Column(db.String(50), nullable=False)
    note_sur_20 = db.Column(db.Float, nullable=True)
    resume = db.Column(db.Text, nullable=True)
    fichier_pdf = db.Column(db.String(200), nullable=True)
    date_soutenance = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Memoire {self.titre}>'

# ==================== FORMULAIRES ====================

class MemoireForm(FlaskForm):
    """Formulaire d'ajout/modification de mémoire"""
    titre = StringField('Titre', validators=[DataRequired()])
    auteur = StringField('Auteur', validators=[DataRequired()])
    annee = IntegerField('Année', validators=[DataRequired(), NumberRange(min=1900, max=2030)])
    filiere = StringField('Filière', validators=[DataRequired()])
    directeur = StringField('Directeur de mémoire', validators=[DataRequired()])
    mention = SelectField('Mention', choices=[
        ('Passable', 'Passable'),
        ('Assez bien', 'Assez bien'),
        ('Bien', 'Bien'),
        ('Très bien', 'Très bien'),
        ('Très honorable', 'Très honorable')
    ], validators=[DataRequired()])
    note_sur_20 = FloatField('Note /20', validators=[Optional(), NumberRange(min=0, max=20)])
    resume = TextAreaField('Résumé')
    date_soutenance = DateField('Date de soutenance', format='%Y-%m-%d', validators=[Optional()])
    fichier_pdf = FileField('Fichier PDF principal (optionnel)')
    fichiers_multiples = MultipleFileField('Fichiers supplémentaires (PDF, DOC, images, etc.)')

# ==================== FONCTIONS UTILITAIRES ====================

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

def envoyer_notification_email(memoire):
    """Envoie un email lors de l'ajout d'un mémoire (optionnel)"""
    if app.config['MAIL_USERNAME']:  # Seulement si email configuré
        try:
            msg = Message(
                subject=f'Nouveau mémoire ajouté - {memoire.titre}',
                recipients=['admin@gasaformation.com'],
                body=f'''
                Un nouveau mémoire a été ajouté dans le système Gasa Formation.
                
                Détails :
                - Titre : {memoire.titre}
                - Auteur : {memoire.auteur}
                - Année : {memoire.annee}
                - Filière : {memoire.filiere}
                - Directeur : {memoire.directeur}
                - Mention : {memoire.mention}
                - Note : {memoire.note_sur_20 if memoire.note_sur_20 else 'Non renseignée'}/20
                
                Consultez-le sur : http://127.0.0.1:5000/fiche/{memoire.id}
                
                Cordialement,
                Système de Gestion des Mémoires - Gasa Formation
                '''
            )
            mail.send(msg)
            print(f"Email envoyé pour le mémoire {memoire.titre}")
        except Exception as e:
            print(f"Erreur d'envoi d'email : {e}")
    else:
        print("Email non configuré - Notification ignorée")

# ==================== ROUTES PRINCIPALES ====================

@app.route('/')
def index():
    """Page d'accueil - Liste des mémoires"""
    search = request.args.get('search', '')
    filtre_annee = request.args.get('annee', '')
    filtre_mention = request.args.get('mention', '')
    
    query = Memoire.query
    
    if search:
        query = query.filter(
            db.or_(
                Memoire.titre.contains(search),
                Memoire.auteur.contains(search),
                Memoire.resume.contains(search)
            )
        )
    if filtre_annee:
        query = query.filter(Memoire.annee == int(filtre_annee))
    if filtre_mention:
        query = query.filter(Memoire.mention == filtre_mention)
    
    memoires = query.order_by(Memoire.date_soutenance.desc()).all()
    
    annees = db.session.query(db.distinct(Memoire.annee)).all()
    mentions = db.session.query(db.distinct(Memoire.mention)).all()
    
    return render_template('index.html', 
                         memoires=memoires, 
                         search=search,
                         filtre_annee=filtre_annee,
                         filtre_mention=filtre_mention,
                         annees=[a[0] for a in annees if a[0]],
                         mentions=[m[0] for m in mentions if m[0]])

@app.route('/ajouter', methods=['GET', 'POST'])
@login_required
def ajouter():
    """Ajouter un nouveau mémoire"""
    form = MemoireForm()
    if form.validate_on_submit():
        # Gestion du fichier PDF principal
        fichier_nom = None
        if form.fichier_pdf.data:
            fichier = form.fichier_pdf.data
            fichier_nom = secure_filename(fichier.filename)
            fichier.save(os.path.join(app.config['UPLOAD_FOLDER'], fichier_nom))
        
        # Création du mémoire
        memoire = Memoire(
            titre=form.titre.data,
            auteur=form.auteur.data,
            annee=form.annee.data,
            filiere=form.filiere.data,
            directeur=form.directeur.data,
            mention=form.mention.data,
            note_sur_20=form.note_sur_20.data,
            resume=form.resume.data,
            date_soutenance=form.date_soutenance.data,
            fichier_pdf=fichier_nom
        )
        db.session.add(memoire)
        db.session.flush()  # Pour obtenir l'ID avant commit
        
        # Gestion des fichiers multiples
        if form.fichiers_multiples.data:
            memoire_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(memoire.id))
            os.makedirs(memoire_folder, exist_ok=True)
            
            for fichier in form.fichiers_multiples.data:
                if fichier and fichier.filename:
                    fichier_nom_multi = secure_filename(fichier.filename)
                    fichier.save(os.path.join(memoire_folder, fichier_nom_multi))
                    
                    doc = Document(
                        memoire_id=memoire.id,
                        nom_fichier=fichier_nom_multi,
                        type_fichier='annexe',
                        description=fichier.filename
                    )
                    db.session.add(doc)
        
        db.session.commit()
        
        # Envoi de notification email (optionnel)
        if app.config['MAIL_USERNAME']:
            envoyer_notification_email(memoire)
        
        flash('Mémoire ajouté avec succès!', 'success')
        return redirect(url_for('index'))
    
    return render_template('ajouter.html', form=form)

@app.route('/modifier/<int:id>', methods=['GET', 'POST'])
@login_required
def modifier(id):
    """Modifier un mémoire existant"""
    memoire = Memoire.query.get_or_404(id)
    form = MemoireForm(obj=memoire)
    
    if form.validate_on_submit():
        memoire.titre = form.titre.data
        memoire.auteur = form.auteur.data
        memoire.annee = form.annee.data
        memoire.filiere = form.filiere.data
        memoire.directeur = form.directeur.data
        memoire.mention = form.mention.data
        memoire.note_sur_20 = form.note_sur_20.data
        memoire.resume = form.resume.data
        memoire.date_soutenance = form.date_soutenance.data
        
        if form.fichier_pdf.data:
            fichier = form.fichier_pdf.data
            fichier_nom = secure_filename(fichier.filename)
            fichier.save(os.path.join(app.config['UPLOAD_FOLDER'], fichier_nom))
            memoire.fichier_pdf = fichier_nom
        
        # Gestion des nouveaux fichiers multiples
        if form.fichiers_multiples.data:
            memoire_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(memoire.id))
            os.makedirs(memoire_folder, exist_ok=True)
            
            for fichier in form.fichiers_multiples.data:
                if fichier and fichier.filename:
                    fichier_nom_multi = secure_filename(fichier.filename)
                    fichier.save(os.path.join(memoire_folder, fichier_nom_multi))
                    
                    doc = Document(
                        memoire_id=memoire.id,
                        nom_fichier=fichier_nom_multi,
                        type_fichier='annexe',
                        description=fichier.filename
                    )
                    db.session.add(doc)
        
        db.session.commit()
        flash('Mémoire modifié avec succès!', 'success')
        return redirect(url_for('index'))
    
    return render_template('modifier.html', form=form, memoire=memoire)

@app.route('/supprimer/<int:id>')
@login_required
def supprimer(id):
    """Supprimer un mémoire"""
    memoire = Memoire.query.get_or_404(id)
    
    # Supprimer le PDF principal
    if memoire.fichier_pdf:
        fichier_path = os.path.join(app.config['UPLOAD_FOLDER'], memoire.fichier_pdf)
        if os.path.exists(fichier_path):
            os.remove(fichier_path)
    
    # Supprimer les documents annexes
    memoire_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(memoire.id))
    if os.path.exists(memoire_folder):
        for fichier in os.listdir(memoire_folder):
            try:
                os.remove(os.path.join(memoire_folder, fichier))
            except:
                pass
        try:
            os.rmdir(memoire_folder)
        except:
            pass
    
    db.session.delete(memoire)
    db.session.commit()
    flash('Mémoire supprimé avec succès!', 'success')
    return redirect(url_for('index'))

@app.route('/fiche/<int:id>')
def fiche(id):
    """Voir la fiche détaillée d'un mémoire"""
    memoire = Memoire.query.get_or_404(id)
    return render_template('fiche.html', memoire=memoire)

@app.route('/export/csv')
@login_required
def export_csv():
    """Exporter tous les mémoires en CSV"""
    memoires = Memoire.query.all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Titre', 'Auteur', 'Année', 'Filière', 'Directeur', 'Mention', 'Note', 'Date soutenance', 'Résumé'])
    
    for m in memoires:
        writer.writerow([m.id, m.titre, m.auteur, m.annee, m.filiere, m.directeur, m.mention, m.note_sur_20, m.date_soutenance, m.resume])
    
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'memoires_gasa_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )

# ==================== EXPORT HTML IMPRIMABLE (PDF sans installation) ====================

@app.route('/export-html/<int:id>')
@login_required
def export_html(id):
    """Exporter la fiche mémoire en HTML imprimable (PDF via navigateur)"""
    memoire = Memoire.query.get_or_404(id)
    return render_template('export_fiche.html', memoire=memoire, datetime=datetime)

# ==================== AUTHENTIFICATION ====================

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Page de connexion"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.find_by_username(username)
        
        if user and user.check_password(password):
            login_user(user)
            flash(f'Bienvenue {username} !', 'success')
            return redirect(url_for('index'))
        else:
            flash('Nom d\'utilisateur ou mot de passe incorrect', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    """Déconnexion"""
    logout_user()
    flash('Déconnexion réussie', 'info')
    return redirect(url_for('index'))

# ==================== STATISTIQUES ====================

@app.route('/statistiques')
@login_required
def statistiques():
    """Page des statistiques avec graphiques"""
    memoires = Memoire.query.all()
    
    # Préparation des données
    data = []
    for m in memoires:
        if m.note_sur_20:
            data.append({
                'année': m.annee,
                'note': m.note_sur_20,
                'mention': m.mention,
                'filiere': m.filiere
            })
    
    if not data:
        flash('Pas assez de données pour générer des statistiques (ajoutez des mémoires avec notes)', 'warning')
        return redirect(url_for('index'))
    
    df = pd.DataFrame(data)
    
    # Graphique 1: Boxplot des notes par année
    fig1, ax1 = plt.subplots(figsize=(10, 6))
    df.boxplot(column='note', by='année', ax=ax1)
    ax1.set_title('Distribution des notes par année', fontsize=14, fontweight='bold')
    ax1.set_xlabel('Année', fontsize=12)
    ax1.set_ylabel('Note /20', fontsize=12)
    plt.suptitle('')
    
    img1 = io.BytesIO()
    plt.savefig(img1, format='png', bbox_inches='tight', dpi=100)
    img1.seek(0)
    graph1 = base64.b64encode(img1.getvalue()).decode()
    plt.close()
    
    # Graphique 2: Répartition des mentions (camembert)
    fig2, ax2 = plt.subplots(figsize=(8, 8))
    mentions_count = df['mention'].value_counts()
    colors = ['#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4', '#ffeaa7']
    ax2.pie(mentions_count.values, labels=mentions_count.index, autopct='%1.1f%%', colors=colors[:len(mentions_count)])
    ax2.set_title('Répartition des mentions', fontsize=14, fontweight='bold')
    
    img2 = io.BytesIO()
    plt.savefig(img2, format='png', bbox_inches='tight', dpi=100)
    img2.seek(0)
    graph2 = base64.b64encode(img2.getvalue()).decode()
    plt.close()
    
    # Graphique 3: Évolution de la moyenne
    fig3, ax3 = plt.subplots(figsize=(10, 6))
    moyennes = df.groupby('année')['note'].mean()
    ax3.plot(moyennes.index, moyennes.values, marker='o', linewidth=2, markersize=8, color='#0d6efd')
    ax3.set_title('Évolution de la note moyenne par année', fontsize=14, fontweight='bold')
    ax3.set_xlabel('Année', fontsize=12)
    ax3.set_ylabel('Note moyenne /20', fontsize=12)
    ax3.grid(True, alpha=0.3)
    for i, (annee, moyenne) in enumerate(moyennes.items()):
        ax3.annotate(f'{moyenne:.1f}', (annee, moyenne), textcoords="offset points", xytext=(0,10), ha='center')
    
    img3 = io.BytesIO()
    plt.savefig(img3, format='png', bbox_inches='tight', dpi=100)
    img3.seek(0)
    graph3 = base64.b64encode(img3.getvalue()).decode()
    plt.close()
    
    # Statistiques générales
    stats = {
        'total_memoires': len(memoires),
        'total_notes': len(df),
        'moyenne_generale': df['note'].mean(),
        'note_min': df['note'].min(),
        'note_max': df['note'].max(),
        'meilleure_mention': df.loc[df['note'].idxmax(), 'mention'] if len(df) > 0 else 'N/A'
    }
    
    return render_template('statistiques.html', graph1=graph1, graph2=graph2, graph3=graph3, stats=stats)

# ==================== ROUTES DE TEST ====================

@app.route('/check-logo')
def check_logo():
    """Vérifier si le logo est présent"""
    logo_path_jpeg = os.path.join('static', 'logo-gasa.jpeg')
    logo_path_jpg = os.path.join('static', 'logo-gasa.jpg')
    
    result = {
        'logo_gasa_jpeg_exists': os.path.exists(logo_path_jpeg),
        'logo_gasa_jpg_exists': os.path.exists(logo_path_jpg),
        'static_folder_contents': os.listdir('static') if os.path.exists('static') else []
    }
    
    return result

@app.route('/test-logo')
def test_logo():
    """Page de test du logo"""
    logo_path = os.path.join('static', 'logo-gasa.jpeg')
    logo_exists = os.path.exists(logo_path)
    
    static_files = []
    if os.path.exists('static'):
        static_files = os.listdir('static')
    
    return f"""
    <h1>Test Logo Gasa Formation</h1>
    <p>Logo trouvé: {logo_exists}</p>
    <p>Chemin: {logo_path}</p>
    <p>Fichiers dans static: {static_files}</p>
    <h2>Aperçu:</h2>
    {f'<img src="/static/logo-gasa.jpeg" style="max-width: 300px; border: 1px solid #ddd; padding: 10px;">' if logo_exists else '<p style="color:red;">Logo non trouvé - Placez logo-gasa.jpeg dans le dossier static/</p>'}
    <br><br>
    <a href="/">Retour à l'accueil</a>
    """

# ==================== LANCEMENT DE L'APPLICATION ====================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    print("\n" + "="*50)
    print("🚀 APPLICATION LANCÉE AVEC SUCCÈS !")
    print("="*50)
    print("\n📌 ACCÈS RAPIDES :")
    print("   • Accueil : http://127.0.0.1:5000")
    print("   • Connexion : http://127.0.0.1:5000/login")
    print("   • Comptes : admin/admin123 ou gasa/gasa2025")
    print("\n📊 FONCTIONNALITÉS DISPONIBLES :")
    print("   ✅ Authentification")
    print("   ✅ Gestion des mémoires (CRUD)")
    print("   ✅ Recherche et filtres")
    print("   ✅ Statistiques avec graphiques")
    print("   ✅ Export CSV")
    print("   ✅ Multi-fichiers (annexes)")
    print("   ✅ Version imprimable / PDF (sans installation)")
    print("\n" + "="*50 + "\n")
    app.run(debug=True, port=5000)