from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, FloatField, TextAreaField, DateField, SelectField, FileField, MultipleFileField, PasswordField
from wtforms.validators import DataRequired, Optional, NumberRange, EqualTo, Length
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
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
from sqlalchemy import distinct

# ==================== CONFIGURATION ====================

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'gasa_formation_2025_secret_key_very_secure')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///memoires.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max

# Configuration Email (optionnelle)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = ''
app.config['MAIL_PASSWORD'] = ''
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
login_manager.login_message_category = 'warning'
mail = Mail(app)

# ==================== MODÈLES DE DONNÉES ====================

class User(UserMixin, db.Model):
    """Modèle utilisateur stocké en base de données"""
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'


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


class ChangePasswordForm(FlaskForm):
    """Formulaire de changement de mot de passe"""
    ancien_mdp = PasswordField('Mot de passe actuel', validators=[DataRequired()])
    nouveau_mdp = PasswordField('Nouveau mot de passe', validators=[
        DataRequired(),
        Length(min=6, message='Le mot de passe doit faire au moins 6 caractères')
    ])
    confirmer_mdp = PasswordField('Confirmer le nouveau mot de passe', validators=[
        DataRequired(),
        EqualTo('nouveau_mdp', message='Les mots de passe ne correspondent pas')
    ])


class AdminChangePasswordForm(FlaskForm):
    """Formulaire admin : changer le mot de passe d'un utilisateur"""
    user_id = SelectField('Utilisateur', coerce=int, validators=[DataRequired()])
    nouveau_mdp = PasswordField('Nouveau mot de passe', validators=[
        DataRequired(),
        Length(min=6, message='Le mot de passe doit faire au moins 6 caractères')
    ])
    confirmer_mdp = PasswordField('Confirmer le nouveau mot de passe', validators=[
        DataRequired(),
        EqualTo('nouveau_mdp', message='Les mots de passe ne correspondent pas')
    ])

# ==================== FONCTIONS UTILITAIRES ====================

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def envoyer_notification_email(memoire):
    """Envoie un email lors de l'ajout d'un mémoire (optionnel)"""
    if app.config['MAIL_USERNAME']:
        try:
            msg = Message(
                subject=f'Nouveau mémoire ajouté - {memoire.titre}',
                recipients=['admin@gasaformation.com'],
                body=f'''
Un nouveau mémoire a été ajouté dans le système Gasa Formation.

Détails :
- Titre     : {memoire.titre}
- Auteur    : {memoire.auteur}
- Année     : {memoire.annee}
- Filière   : {memoire.filiere}
- Directeur : {memoire.directeur}
- Mention   : {memoire.mention}
- Note      : {memoire.note_sur_20 if memoire.note_sur_20 else "Non renseignée"}/20

Consultez-le sur : /fiche/{memoire.id}

Cordialement,
Système de Gestion des Mémoires - Gasa Formation
                '''
            )
            mail.send(msg)
        except Exception as e:
            print(f"Erreur d'envoi d'email : {e}")

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

    annees = db.session.execute(db.select(distinct(Memoire.annee))).scalars().all()
    mentions = db.session.execute(db.select(distinct(Memoire.mention))).scalars().all()

    return render_template('index.html',
                           memoires=memoires,
                           search=search,
                           filtre_annee=filtre_annee,
                           filtre_mention=filtre_mention,
                           annees=sorted([a for a in annees if a], reverse=True),
                           mentions=[m for m in mentions if m])


@app.route('/ajouter', methods=['GET', 'POST'])
@login_required
def ajouter():
    """Ajouter un nouveau mémoire"""
    form = MemoireForm()
    if form.validate_on_submit():
        fichier_nom = None
        if form.fichier_pdf.data and form.fichier_pdf.data.filename:
            fichier = form.fichier_pdf.data
            fichier_nom = secure_filename(fichier.filename)
            fichier.save(os.path.join(app.config['UPLOAD_FOLDER'], fichier_nom))

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
        db.session.flush()

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
        envoyer_notification_email(memoire)
        flash('Mémoire ajouté avec succès !', 'success')
        return redirect(url_for('index'))

    return render_template('ajouter.html', form=form)


@app.route('/modifier/<int:id>', methods=['GET', 'POST'])
@login_required
def modifier(id):
    """Modifier un mémoire existant"""
    memoire = db.get_or_404(Memoire, id)
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

        if form.fichier_pdf.data and form.fichier_pdf.data.filename:
            fichier = form.fichier_pdf.data
            fichier_nom = secure_filename(fichier.filename)
            fichier.save(os.path.join(app.config['UPLOAD_FOLDER'], fichier_nom))
            memoire.fichier_pdf = fichier_nom

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
        flash('Mémoire modifié avec succès !', 'success')
        return redirect(url_for('fiche', id=memoire.id))

    return render_template('modifier.html', form=form, memoire=memoire)


@app.route('/supprimer/<int:id>', methods=['POST'])
@login_required
def supprimer(id):
    """Supprimer un mémoire (POST uniquement pour sécurité)"""
    memoire = db.get_or_404(Memoire, id)

    if memoire.fichier_pdf:
        fichier_path = os.path.join(app.config['UPLOAD_FOLDER'], memoire.fichier_pdf)
        if os.path.exists(fichier_path):
            os.remove(fichier_path)

    memoire_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(memoire.id))
    if os.path.exists(memoire_folder):
        for fichier in os.listdir(memoire_folder):
            try:
                os.remove(os.path.join(memoire_folder, fichier))
            except OSError:
                pass
        try:
            os.rmdir(memoire_folder)
        except OSError:
            pass

    db.session.delete(memoire)
    db.session.commit()
    flash('Mémoire supprimé avec succès !', 'success')
    return redirect(url_for('index'))


@app.route('/fiche/<int:id>')
def fiche(id):
    """Voir la fiche détaillée d'un mémoire"""
    memoire = db.get_or_404(Memoire, id)
    return render_template('fiche.html', memoire=memoire)


@app.route('/export/csv')
@login_required
def export_csv():
    """Exporter tous les mémoires en CSV"""
    memoires = Memoire.query.order_by(Memoire.annee.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Titre', 'Auteur', 'Année', 'Filière', 'Directeur', 'Mention', 'Note', 'Date soutenance', 'Résumé'])

    for m in memoires:
        writer.writerow([
            m.id, m.titre, m.auteur, m.annee, m.filiere,
            m.directeur, m.mention, m.note_sur_20,
            m.date_soutenance.strftime('%d/%m/%Y') if m.date_soutenance else '',
            m.resume
        ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'memoires_gasa_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )


@app.route('/export-html/<int:id>')
@login_required
def export_html(id):
    """Exporter la fiche mémoire en HTML imprimable"""
    memoire = db.get_or_404(Memoire, id)
    return render_template('export_fiche.html', memoire=memoire, datetime=datetime)

# ==================== AUTHENTIFICATION ====================

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Page de connexion"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            flash(f'Bienvenue {username} !', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash("Nom d'utilisateur ou mot de passe incorrect.", 'danger')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    """Déconnexion"""
    logout_user()
    flash('Déconnexion réussie.', 'info')
    return redirect(url_for('index'))

# ==================== CHANGEMENT DE MOT DE PASSE ====================

@app.route('/mon-compte/changer-mdp', methods=['GET', 'POST'])
@login_required
def changer_mdp():
    """Changer son propre mot de passe"""
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.ancien_mdp.data):
            flash('Mot de passe actuel incorrect.', 'danger')
            return render_template('changer_mdp.html', form=form)

        current_user.set_password(form.nouveau_mdp.data)
        db.session.commit()
        flash('Mot de passe modifié avec succès !', 'success')
        return redirect(url_for('index'))

    return render_template('changer_mdp.html', form=form)


@app.route('/admin/gestion-utilisateurs', methods=['GET', 'POST'])
@login_required
def gestion_utilisateurs():
    """Admin : gérer les mots de passe de tous les utilisateurs"""
    if not current_user.is_admin:
        flash("Accès refusé. Vous devez être administrateur.", 'danger')
        return redirect(url_for('index'))

    form = AdminChangePasswordForm()
    users = User.query.all()
    form.user_id.choices = [(u.id, u.username) for u in users]

    if form.validate_on_submit():
        target_user = db.session.get(User, form.user_id.data)
        if target_user:
            target_user.set_password(form.nouveau_mdp.data)
            db.session.commit()
            flash(f'Mot de passe de « {target_user.username} » modifié avec succès !', 'success')
        else:
            flash('Utilisateur introuvable.', 'danger')
        return redirect(url_for('gestion_utilisateurs'))

    return render_template('gestion_utilisateurs.html', form=form, users=users)

# ==================== STATISTIQUES ====================

@app.route('/statistiques')
@login_required
def statistiques():
    """Page des statistiques avec graphiques"""
    memoires = Memoire.query.all()

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
        flash('Pas assez de données pour générer des statistiques (ajoutez des mémoires avec notes).', 'warning')
        return redirect(url_for('index'))

    df = pd.DataFrame(data)

    # Graphique 1 : Boxplot des notes par année
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

    # Graphique 2 : Répartition des mentions
    fig2, ax2 = plt.subplots(figsize=(8, 8))
    mentions_count = df['mention'].value_counts()
    colors = ['#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4', '#ffeaa7']
    ax2.pie(mentions_count.values, labels=mentions_count.index,
            autopct='%1.1f%%', colors=colors[:len(mentions_count)])
    ax2.set_title('Répartition des mentions', fontsize=14, fontweight='bold')
    img2 = io.BytesIO()
    plt.savefig(img2, format='png', bbox_inches='tight', dpi=100)
    img2.seek(0)
    graph2 = base64.b64encode(img2.getvalue()).decode()
    plt.close()

    # Graphique 3 : Évolution de la moyenne
    fig3, ax3 = plt.subplots(figsize=(10, 6))
    moyennes = df.groupby('année')['note'].mean()
    ax3.plot(moyennes.index, moyennes.values, marker='o', linewidth=2,
             markersize=8, color='#0d6efd')
    ax3.set_title('Évolution de la note moyenne par année', fontsize=14, fontweight='bold')
    ax3.set_xlabel('Année', fontsize=12)
    ax3.set_ylabel('Note moyenne /20', fontsize=12)
    ax3.grid(True, alpha=0.3)
    for annee, moyenne in moyennes.items():
        ax3.annotate(f'{moyenne:.1f}', (annee, moyenne),
                     textcoords="offset points", xytext=(0, 10), ha='center')
    img3 = io.BytesIO()
    plt.savefig(img3, format='png', bbox_inches='tight', dpi=100)
    img3.seek(0)
    graph3 = base64.b64encode(img3.getvalue()).decode()
    plt.close()

    stats = {
        'total_memoires': len(memoires),
        'total_notes': len(df),
        'moyenne_generale': df['note'].mean(),
        'note_min': df['note'].min(),
        'note_max': df['note'].max(),
        'meilleure_mention': df.loc[df['note'].idxmax(), 'mention'] if len(df) > 0 else 'N/A'
    }

    return render_template('statistiques.html',
                           graph1=graph1, graph2=graph2, graph3=graph3,
                           stats=stats)

# ==================== INITIALISATION DE LA BASE (POUR RENDER) ====================
# Ce bloc s'exécute au démarrage de l'application sur Render

with app.app_context():
    # Créer toutes les tables si elles n'existent pas
    db.create_all()
    
    # Créer les comptes par défaut si la table user est vide
    if User.query.count() == 0:
        admin = User(username='admin', is_admin=True)
        admin.set_password('admin123')
        gasa = User(username='gasa', is_admin=False)
        gasa.set_password('gasa2025')
        db.session.add_all([admin, gasa])
        db.session.commit()
        print("✅ Comptes créés : admin/admin123 | gasa/gasa2025")
        print("✅ Base de données initialisée avec succès !")

# ==================== LANCEMENT ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("\n" + "="*50)
    print("  Gestion des Mémoires - Gasa Formation")
    print("="*50)
    print(f"  Accès   : http://0.0.0.0:{port}")
    print("  Comptes : admin/admin123  |  gasa/gasa2025")
    print("="*50 + "\n")
    app.run(debug=False, host='0.0.0.0', port=port)