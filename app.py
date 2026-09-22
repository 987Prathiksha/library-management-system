import os
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, Book, IssueLog, Fine

app = Flask(__name__)
app.config['SECRET_KEY'] = 'library-secret-key-super-secure-2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///library.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Access denied. Administrator privileges required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def update_overdue_statuses():
    """Helper to refresh overdue statuses and calculate pending fines."""
    now = datetime.utcnow()
    active_issues = IssueLog.query.filter(IssueLog.status.in_(['issued', 'overdue'])).all()
    for issue in active_issues:
        if now > issue.due_date:
            issue.status = 'overdue'
            fine_amount = issue.calculate_fine(rate_per_day=1.0)
            existing_fine = Fine.query.filter_by(issue_id=issue.id).first()
            if existing_fine:
                if existing_fine.status == 'unpaid':
                    existing_fine.amount = fine_amount
            else:
                if fine_amount > 0:
                    new_fine = Fine(issue_id=issue.id, user_id=issue.user_id, amount=fine_amount, status='unpaid')
                    db.session.add(new_fine)
    db.session.commit()


# ----------------------------------------------------
# AUTHENTICATION ROUTES
# ----------------------------------------------------

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash(f'Welcome back, {user.username}!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'danger')

    return render_template('auth/login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        if not username or not email or not password:
            flash('All fields are required.', 'danger')
            return render_template('auth/register.html')

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/register.html')

        if User.query.filter_by(username=username).first():
            flash('Username is already taken.', 'warning')
            return render_template('auth/register.html')

        if User.query.filter_by(email=email).first():
            flash('Email is already registered.', 'warning')
            return render_template('auth/register.html')

        new_user = User(username=username, email=email, role='student')
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        flash('Registration successful! You can now log in.', 'success')
        return redirect(url_for('login'))

    return render_template('auth/register.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ----------------------------------------------------
# DASHBOARD ROUTE
# ----------------------------------------------------

@app.route('/dashboard')
@login_required
def dashboard():
    update_overdue_statuses()

    if current_user.is_admin:
        total_books = Book.query.count()
        total_users = User.query.filter_by(role='student').count()
        active_issues_count = IssueLog.query.filter(IssueLog.status.in_(['issued', 'overdue'])).count()
        unpaid_fines_sum = db.session.query(db.func.sum(Fine.amount)).filter_by(status='unpaid').scalar() or 0.0
        recent_issues = IssueLog.query.order_by(IssueLog.issue_date.desc()).limit(5).all()

        return render_template('dashboard/admin.html',
                               total_books=total_books,
                               total_users=total_users,
                               active_issues_count=active_issues_count,
                               unpaid_fines_sum=unpaid_fines_sum,
                               recent_issues=recent_issues)
    else:
        active_issues = IssueLog.query.filter_by(user_id=current_user.id).filter(IssueLog.status.in_(['issued', 'overdue'])).all()
        user_unpaid_fines = Fine.query.filter_by(user_id=current_user.id, status='unpaid').all()
        total_user_fine = sum(f.amount for f in user_unpaid_fines)
        recent_history = IssueLog.query.filter_by(user_id=current_user.id).order_by(IssueLog.issue_date.desc()).limit(5).all()

        return render_template('dashboard/student.html',
                               active_issues=active_issues,
                               total_user_fine=total_user_fine,
                               recent_history=recent_history)


# ----------------------------------------------------
# BOOK MANAGEMENT ROUTES
# ----------------------------------------------------

@app.route('/books')
@login_required
def book_list():
    query = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()

    books_query = Book.query

    if query:
        search_filter = f"%{query}%"
        books_query = books_query.filter(
            (Book.title.ilike(search_filter)) |
            (Book.author.ilike(search_filter)) |
            (Book.isbn.ilike(search_filter))
        )

    if category:
        books_query = books_query.filter_by(category=category)

    books = books_query.order_by(Book.title.asc()).all()
    categories = db.session.query(Book.category).distinct().all()
    category_list = [c[0] for c in categories if c[0]]

    return render_template('books/list.html', books=books, categories=category_list, search_query=query, selected_category=category)


@app.route('/books/<int:book_id>')
@login_required
def book_detail(book_id):
    book = Book.query.get_or_404(book_id)
    user_has_issued = IssueLog.query.filter_by(
        user_id=current_user.id, book_id=book.id
    ).filter(IssueLog.status.in_(['issued', 'overdue'])).first()

    return render_template('books/detail.html', book=book, user_has_issued=user_has_issued)


@app.route('/admin/books/add', methods=['GET', 'POST'])
@login_required
@admin_required
def book_add():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        author = request.form.get('author', '').strip()
        isbn = request.form.get('isbn', '').strip()
        category = request.form.get('category', 'General').strip()
        quantity = int(request.form.get('quantity', 1))
        cover_url = request.form.get('cover_url', '').strip()
        description = request.form.get('description', '').strip()

        if not title or not author or quantity < 1:
            flash('Title, Author, and a positive quantity are required.', 'danger')
            return render_template('books/form.html', action='Add', book=None)

        if isbn and Book.query.filter_by(isbn=isbn).first():
            flash('ISBN already exists in the catalog.', 'warning')
            return render_template('books/form.html', action='Add', book=None)

        new_book = Book(
            title=title,
            author=author,
            isbn=isbn if isbn else None,
            category=category,
            quantity=quantity,
            available_quantity=quantity,
            cover_url=cover_url if cover_url else None,
            description=description
        )
        db.session.add(new_book)
        db.session.commit()

        flash(f'Book "{title}" added successfully!', 'success')
        return redirect(url_for('book_list'))

    return render_template('books/form.html', action='Add', book=None)


@app.route('/admin/books/edit/<int:book_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def book_edit(book_id):
    book = Book.query.get_or_404(book_id)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        author = request.form.get('author', '').strip()
        isbn = request.form.get('isbn', '').strip()
        category = request.form.get('category', 'General').strip()
        new_quantity = int(request.form.get('quantity', 1))
        cover_url = request.form.get('cover_url', '').strip()
        description = request.form.get('description', '').strip()

        if not title or not author or new_quantity < 1:
            flash('Title, Author, and a positive quantity are required.', 'danger')
            return render_template('books/form.html', action='Edit', book=book)

        existing_isbn = Book.query.filter(Book.isbn == isbn, Book.id != book.id).first()
        if isbn and existing_isbn:
            flash('ISBN already assigned to another book.', 'warning')
            return render_template('books/form.html', action='Edit', book=book)

        # Calculate updated available quantity based on change in total quantity
        issued_count = book.quantity - book.available_quantity
        if new_quantity < issued_count:
            flash(f'Cannot decrease total quantity below currently issued count ({issued_count}).', 'danger')
            return render_template('books/form.html', action='Edit', book=book)

        book.title = title
        book.author = author
        book.isbn = isbn if isbn else None
        book.category = category
        book.quantity = new_quantity
        book.available_quantity = new_quantity - issued_count
        book.cover_url = cover_url if cover_url else None
        book.description = description

        db.session.commit()
        flash(f'Book "{title}" updated successfully!', 'success')
        return redirect(url_for('book_list'))

    return render_template('books/form.html', action='Edit', book=book)


@app.route('/admin/books/delete/<int:book_id>', methods=['POST'])
@login_required
@admin_required
def book_delete(book_id):
    book = Book.query.get_or_404(book_id)
    active_issues = IssueLog.query.filter_by(book_id=book.id).filter(IssueLog.status.in_(['issued', 'overdue'])).first()
    
    if active_issues:
        flash(f'Cannot delete "{book.title}" because it currently has active issue records.', 'danger')
        return redirect(url_for('book_list'))

    db.session.delete(book)
    db.session.commit()
    flash(f'Book "{book.title}" deleted from catalog.', 'success')
    return redirect(url_for('book_list'))


# ----------------------------------------------------
# CIRCULATION & ISSUE LOG ROUTES
# ----------------------------------------------------

@app.route('/books/<int:book_id>/issue', methods=['POST'])
@login_required
def issue_book(book_id):
    book = Book.query.get_or_404(book_id)

    if book.available_quantity <= 0:
        flash('Sorry, this book is currently out of stock.', 'warning')
        return redirect(url_for('book_detail', book_id=book.id))

    existing_issue = IssueLog.query.filter_by(
        user_id=current_user.id, book_id=book.id
    ).filter(IssueLog.status.in_(['issued', 'overdue'])).first()

    if existing_issue:
        flash('You have already issued this book.', 'info')
        return redirect(url_for('book_detail', book_id=book.id))

    # Create Issue Record (14-day borrowing period)
    due_date = datetime.utcnow() + timedelta(days=14)
    new_issue = IssueLog(user_id=current_user.id, book_id=book.id, due_date=due_date, status='issued')
    
    book.available_quantity -= 1

    db.session.add(new_issue)
    db.session.commit()

    flash(f'Successfully issued "{book.title}". Due date: {due_date.strftime("%Y-%m-%d")}.', 'success')
    return redirect(url_for('issue_list'))


@app.route('/issues')
@login_required
def issue_list():
    update_overdue_statuses()

    if current_user.is_admin:
        issues = IssueLog.query.order_by(IssueLog.issue_date.desc()).all()
    else:
        issues = IssueLog.query.filter_by(user_id=current_user.id).order_by(IssueLog.issue_date.desc()).all()

    return render_template('issues/list.html', issues=issues)


@app.route('/issues/<int:issue_id>/return', methods=['POST'])
@login_required
def return_book(issue_id):
    issue = IssueLog.query.get_or_404(issue_id)

    if not current_user.is_admin and issue.user_id != current_user.id:
        flash('Unauthorized action.', 'danger')
        return redirect(url_for('issue_list'))

    if issue.status == 'returned':
        flash('This book has already been returned.', 'info')
        return redirect(url_for('issue_list'))

    now = datetime.utcnow()
    issue.return_date = now
    issue.status = 'returned'

    book = Book.query.get(issue.book_id)
    if book:
        book.available_quantity += 1

    # Check for fine
    fine_amount = issue.calculate_fine(rate_per_day=1.0)
    if fine_amount > 0:
        existing_fine = Fine.query.filter_by(issue_id=issue.id).first()
        if existing_fine:
            existing_fine.amount = fine_amount
        else:
            new_fine = Fine(issue_id=issue.id, user_id=issue.user_id, amount=fine_amount, status='unpaid')
            db.session.add(new_fine)
        flash(f'Book returned. An overdue fine of ${fine_amount:.2f} has been incurred.', 'warning')
    else:
        flash(f'Book "{book.title if book else ""}" returned successfully!', 'success')

    db.session.commit()
    return redirect(url_for('issue_list'))


# ----------------------------------------------------
# FINE MANAGEMENT ROUTES
# ----------------------------------------------------

@app.route('/fines')
@login_required
def fine_list():
    update_overdue_statuses()

    if current_user.is_admin:
        fines = Fine.query.order_by(Fine.created_at.desc()).all()
    else:
        fines = Fine.query.filter_by(user_id=current_user.id).order_by(Fine.created_at.desc()).all()

    total_unpaid = sum(f.amount for f in fines if f.status == 'unpaid')
    return render_template('fines/list.html', fines=fines, total_unpaid=total_unpaid)


@app.route('/fines/<int:fine_id>/pay', methods=['POST'])
@login_required
def pay_fine(fine_id):
    fine = Fine.query.get_or_404(fine_id)

    if not current_user.is_admin and fine.user_id != current_user.id:
        flash('Unauthorized action.', 'danger')
        return redirect(url_for('fine_list'))

    if fine.status == 'paid':
        flash('This fine has already been paid.', 'info')
        return redirect(url_for('fine_list'))

    fine.status = 'paid'
    fine.paid_at = datetime.utcnow()
    db.session.commit()

    flash(f'Fine of ${fine.amount:.2f} marked as PAID. Thank you!', 'success')
    return redirect(url_for('fine_list'))


# ----------------------------------------------------
# DATABASE SEED & INITIALIZATION
# ----------------------------------------------------

def seed_database():
    with app.app_context():
        db.create_all()

        # Seed Admin User
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin', email='admin@library.com', role='admin')
            admin.set_password('admin123')
            db.session.add(admin)

        # Seed Sample Student User
        student = User.query.filter_by(username='student').first()
        if not student:
            student = User(username='student', email='student@library.com', role='student')
            student.set_password('student123')
            db.session.add(student)

        # Seed Sample Books
        if Book.query.count() == 0:
            sample_books = [
                Book(
                    title='Clean Code: A Handbook of Agile Software Craftsmanship',
                    author='Robert C. Martin',
                    isbn='978-0132350884',
                    category='Computer Science',
                    quantity=5,
                    available_quantity=5,
                    cover_url='https://images.unsplash.com/photo-1532012197267-da84d127e765?auto=format&fit=crop&w=400&q=80',
                    description='Even bad code can function. But if code isn’t clean, it can bring a development organization to its knees.'
                ),
                Book(
                    title='Design Patterns: Elements of Reusable Object-Oriented Software',
                    author='Erich Gamma, Richard Helm, Ralph Johnson, John Vlissides',
                    isbn='978-0201633610',
                    category='Computer Science',
                    quantity=3,
                    available_quantity=3,
                    cover_url='https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?auto=format&fit=crop&w=400&q=80',
                    description='Capturing a wealth of experience about the design of object-oriented software, four top-notch designers present a catalog of simple and succinct solutions to commonly occurring design problems.'
                ),
                Book(
                    title='Dune',
                    author='Frank Herbert',
                    isbn='978-0441172719',
                    category='Science Fiction',
                    quantity=4,
                    available_quantity=4,
                    cover_url='https://images.unsplash.com/photo-1512820790803-83ca734da794?auto=format&fit=crop&w=400&q=80',
                    description='Set on the desert planet Arrakis, Dune is the story of the boy Paul Atreides, heir to a noble family tasked with ruling an inhospitable world.'
                ),
                Book(
                    title='To Kill a Mockingbird',
                    author='Harper Lee',
                    isbn='978-0061120084',
                    category='Classics',
                    quantity=6,
                    available_quantity=6,
                    cover_url='https://images.unsplash.com/photo-1543002588-bfa74002ed7e?auto=format&fit=crop&w=400&q=80',
                    description='The unforgettable novel of a childhood in a sleepy Southern town and the crisis of conscience that rocked it.'
                ),
                Book(
                    title='The Pragmatic Programmer',
                    author='David Thomas, Andrew Hunt',
                    isbn='978-0135957059',
                    category='Computer Science',
                    quantity=2,
                    available_quantity=2,
                    cover_url='https://images.unsplash.com/photo-1524995997946-a1c2e315a42f?auto=format&fit=crop&w=400&q=80',
                    description='The Pragmatic Programmer cuts through the increasing specialization and technicalities of modern software development to examine the core process.'
                )
            ]
            db.session.add_all(sample_books)

        db.session.commit()


if __name__ == '__main__':
    seed_database()
    app.run(debug=True, port=5000)
