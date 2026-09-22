from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='student')  # 'admin' or 'student'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    issue_logs = db.relationship('IssueLog', backref='user', lazy=True, cascade="all, delete-orphan")
    fines = db.relationship('Fine', backref='user', lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


class Book(db.Model):
    __tablename__ = 'books'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(150), nullable=False)
    isbn = db.Column(db.String(50), unique=True, nullable=True)
    category = db.Column(db.String(80), nullable=False, default='General')
    quantity = db.Column(db.Integer, nullable=False, default=1)
    available_quantity = db.Column(db.Integer, nullable=False, default=1)
    cover_url = db.Column(db.String(500), nullable=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    issue_logs = db.relationship('IssueLog', backref='book', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Book {self.title}>'


class IssueLog(db.Model):
    __tablename__ = 'issue_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    issue_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    due_date = db.Column(db.DateTime, nullable=False)
    return_date = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='issued')  # 'issued', 'returned', 'overdue'

    # Relationships
    fines = db.relationship('Fine', backref='issue_log', lazy=True, cascade="all, delete-orphan")

    def calculate_fine(self, rate_per_day=1.0):
        """Calculate fine if returned after due_date or currently overdue."""
        compare_date = self.return_date if self.return_date else datetime.utcnow()
        if compare_date > self.due_date:
            delta_days = (compare_date - self.due_date).days
            if (compare_date - self.due_date).seconds > 0 and delta_days == 0:
                delta_days = 1
            return round(delta_days * rate_per_day, 2)
        return 0.0

    def __repr__(self):
        return f'<IssueLog User:{self.user_id} Book:{self.book_id} Status:{self.status}>'


class Fine(db.Model):
    __tablename__ = 'fines'
    
    id = db.Column(db.Integer, primary_key=True)
    issue_id = db.Column(db.Integer, db.ForeignKey('issue_logs.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False, default=0.0)
    status = db.Column(db.String(20), nullable=False, default='unpaid')  # 'unpaid', 'paid'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f'<Fine Issue:{self.issue_id} Amount:${self.amount} Status:{self.status}>'
