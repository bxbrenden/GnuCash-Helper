"""Utility functions for GnuCash Helper."""
import logging
from os import environ as env
import sys

import piecash
from piecash import Transaction, Split, GnucashException


def configure_logging():
    """Set up logging for the module."""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    fh = logging.FileHandler('/gnucash-helper.log', encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s  %(name)s  %(levelname)s:%(message)s')
    ch.setFormatter(formatter)
    fh.setFormatter(formatter)
    logger.addHandler(ch)
    logger.addHandler(fh)

    return logger


logger = configure_logging()


def get_env_var(name):
    """Get the environment variable `name` from environment variable.

    Return the value of the `name` env var if found, None otherwise.
    """
    try:
        env_var = env[name]
    except KeyError as ke:
        logger.critical(f'Could not get env. var. "{ke}". Make sure it is set')
    else:
        return env_var


def get_book_name_from_env():
    """Get the GnuCash book name from an environment variable."""
    try:
        book_name = env['GNUCASH_FILE']
    except KeyError as ke:
        logger.critical(f'Could not get GnuCash book name from env. var. {ke}.')
        sys.exit(1)
    else:
        return book_name


def open_book(book_name, readonly=False, open_if_lock=True, do_backup=False):
    """Open a GnuCash book for reading and potentially writing."""
    try:
        book = piecash.open_book(book_name, readonly=readonly, open_if_lock=open_if_lock, do_backup=do_backup)
    except GnucashException as gce:
        logger.critical(f'Error while attempting to open GnuCash book "{book_name}"')
        logger.critical(gce)
        sys.exit(1)
    else:
        return book


def list_accounts(book):
    """List accounts in an existing book.

    `book` should be the fully qualified path to the GnuCash book.
    """
    book = open_book(book, readonly=True)
    accounts = sorted([x.fullname for x in book.accounts])
    book.close()

    return accounts


def get_account(account_name, book):
    """Return a piecash Account object that matches `account_name`.

    Return None if no match is found.
    """
    accounts = book.accounts
    search_name = account_name.lower()
    for account in accounts:
        if account.fullname.lower() == search_name:
            return account

    return None


def add_account(book, new_acct_name, parent, currency='USD'):
    """Add a GnuCash account with name `new_acct_name` and a parent account of `parent`.

    Optionally set USD
    """
    parent_account = book.accounts.get(fullname=parent)
    if parent_account:
        child_accts = [child.name.lower() for child in parent_account.children]
        if new_acct_name.lower() in child_accts:
            logger.warning(f'The {new_acct_name} account already exists as a child of your {parent} account. Skipping')
            return False
    else:
        logger.error(f'There was no parent account named "{parent}"')
        return False

    USD = book.commodities.get(mnemonic='USD')
    if parent_account and USD:
        new_account = piecash.Account(name=new_acct_name,
                                      type='EXPENSE',
                                      parent=parent_account,
                                      commodity=USD)
        try:
            book.save()
        except GnucashException as gce:
            logger.critical('Encounted GnuCash Error while saving book:')
            logger.critical(gce)
            sys.exit(1)
        else:
            logger.info(f'Successfully saved book with new account "{new_acct_name}", child of parent account "{parent}"')
            return True

    else:
        logger.error(f'There was no parent account named "{parent}" or no commodity named "USD"')
        return False


def last_n_transactions(book, n=50):
    """Return the last `n` transactions from the GnuCash book `book`.

    The transactions are returned as a dict where the items are:
    - source: source account name
    - dest: destination account name
    - date: the enter date of the transaction (e.g. 2021-01-01)
    - amount: the amount of money
    """
    last_n = []
    transactions = [x for x in reversed(book.transactions[-n:])]
    logger.debug(f'`n` was set to {n} for getting last transactions')
    logger.debug(f'There are {len(transactions)} transactions in the list')

    for ind, trans in enumerate(transactions):
        t = {}
        date = str(trans.enter_date.date())
        splits = trans.splits
        logger.debug(f'Txn #{ind}: the length of `splits` is: {len(splits)}')
        logger.debug('The splits are:')
        for split in splits:
            logger.debug(split)
        if len(splits) != 2:
            logger.error(f'The length of splits was not 2 for transaction #{ind}. Skipping.')
            continue

        # figure out which split contains the debit acct in the transaction
        if splits[0].is_debit:
            source_acct = splits[1]
            dest_acct = splits[0]
        else:
            source_acct = splits[0]
            dest_acct = splits[1]

        descrip = trans.description
        amount = dest_acct.value
        # make the amount positive for display's sake
        if amount.is_signed():
            amount = -amount
        amount = float(amount)

        t['date'] = date
        t['source'] = source_acct.account.fullname
        t['dest'] = dest_acct.account.fullname
        t['description'] = descrip
        t['amount'] = f'${amount:.2f}'
        last_n.append(t)

    return last_n


def add_transaction(book, description, amount, debit_acct, credit_acct):
    """Add a transaction to an existing book.

    `amount` should be a float out to 2 decimal places for the value of the transaction.
    `debit_acct` and `credit_acct` should be the names of the accounts as given by the .fullname
    method from a GnuCash Account, e.g. book.accounts.get(fullname="Expenses:Food").
    """
    try:
        credit = get_account(credit_acct, book)
        debit = get_account(debit_acct, book)
        if credit and debit:
            usd = book.currencies(mnemonic='USD')
            logger.info('Creating a new transaction in the GnuCash book.')
            transaction = Transaction(currency=usd,
                                      description=description,
                                      splits=[
                                          Split(value=amount, account=credit),
                                          Split(value=-amount, account=debit)
                                      ])
            book.save()
            logger.info('Successfully saved transaction')
            return True

        elif credit and not debit:
            logger.error(f'The debit account {debit_acct} was not found. Skipping.')
            return False

        elif debit and not credit:
            logger.error(f'The credit account {credit_acct} was not found. Skipping.')
            return False

    except GnucashException as gce:
        logger.error('Failed to add the transaction')
        logger.error(gce)
        return False

    except ValueError as ve:
        logger.error('Failed to add the transaction with ValueError:')
        logger.error(ve)
        return False


def get_gnucash_dir():
    """Get the fully qualified path of the directory of your .gnucash file."""
    try:
        gnucash_dir = env['GNUCASH_DIR']
    except KeyError as ke:
        logger.critical(f'Error, could not get GnuCash directory {ke} from env var')
        logger.critical('Make sure to set $GNUCASH_DIR')
        sys.exit(1)
    else:
        return gnucash_dir
