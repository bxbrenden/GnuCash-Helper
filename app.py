from gnucash_helper import list_accounts,\
                           get_book_name_from_env,\
                           open_book,\
                           add_transaction,\
                           get_gnucash_dir,\
                           last_n_transactions,\
                           get_env_var,\
                           logger

from decimal import ROUND_HALF_UP
import os
from os import environ as env

from flask import Flask, render_template, redirect, url_for, flash
from flask_bootstrap import Bootstrap
from flask_wtf import FlaskForm
from wtforms import DecimalField,\
                    SelectField,\
                    SubmitField,\
                    TextAreaField

from wtforms.validators import DataRequired

book_name = get_book_name_from_env()
gnucash_dir = get_gnucash_dir()
path_to_book = gnucash_dir + '/' + book_name
book_exists = os.path.exists(path_to_book)
logger.info(f'At the global start, the book\'s existence is: {book_exists}')


class TransactionForm(FlaskForm):
    debit = SelectField('From Account (Debit)',
                        validators=[DataRequired()],
                        validate_choice=True)
    credit = SelectField('To Account (Credit)',
                         validators=[DataRequired()],
                         validate_choice=True)
    amount = DecimalField('Amount ($)',
                          validators=[DataRequired('Do not include a dollar sign or a comma.')],
                          places=2,
                          rounding=ROUND_HALF_UP,
                          render_kw={'placeholder': 'Ex: 4.20'})
    description = TextAreaField('Description', validators=[DataRequired()])
    submit = SubmitField('Submit')

    @classmethod
    def new(cls):
        """Instantiate a new TransactionForm."""
        global path_to_book
        global logger
        logger.info('Attempting to read GnuCash book to create TransactionForm.')
        accounts = list_accounts(path_to_book)
        txn_form = cls()
        txn_form.debit.choices = accounts
        txn_form.credit.choices = accounts

        return txn_form


app = Flask(__name__)
app.config['SECRET_KEY'] = env.get('FLASK_SECRET_KEY',
                                   'Mjpe[){i>"r3}]Fm+-{7#,m}qFtf!w)T')
bootstrap = Bootstrap(app)


@app.route('/', methods=['GET', 'POST'])
def index():
    global logger
    logger.info('Creating new form inside of the index route')
    form = TransactionForm.new()
    if form.validate_on_submit():
        # Add the transaction to the GnuCash book
        logger.info('Attempting to open book in index route')
        gnucash_book = open_book(path_to_book)
        descrip = form.description.data
        amount = form.amount.data
        credit = form.credit.data
        debit = form.debit.data
        added_txn = add_transaction(gnucash_book, descrip, amount, debit, credit)
        gnucash_book.close()

        if added_txn:
            flash(f'Transaction for {float(amount):.2f} saved to GnuCash file.',
                  'success')
        else:
            flash(f'Transaction for {float(amount):.2f} was not saved to GnuCash file.',
                  'danger')

        return redirect(url_for('index'))
    return render_template('index.html', form=form)


@app.route('/transactions')
def transactions():
    global path_to_book
    global logger
    logger.info('Attempting to open book inside transactions route')
    book = open_book(path_to_book)

    # determine the number of transactions to display based on env var
    num_transactions = int(get_env_var('NUM_TRANSACTIONS'))
    if num_transactions is None:
        transactions = last_n_transactions(book)
    else:
        transactions = last_n_transactions(book, n=num_transactions)
    book.close()

    return render_template('transactions.html',
                           transactions=transactions,
                           n=num_transactions)


@app.route('/balances')
def balances():
    global path_to_book
    global logger
    logger.info('Attempting to open book inside of balances route.')
    book = open_book(path_to_book, readonly=True)
    accounts = []
    for acc in book.accounts:
        account = {}
        fn = acc.fullname.replace(':', ' ➔ ')
        bal = acc.get_balance()
        bal = f'${bal:,.2f}'
        account['fullname'] = fn
        account['balance'] = bal
        accounts.append(account)
    accounts = sorted(accounts, key=lambda x: x['fullname'])
    book.close()

    return render_template('balances.html',
                           accounts=accounts)


@app.errorhandler(404)
def page_nout_found(e):
    return render_template('404.html')


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html')
