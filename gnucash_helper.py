import logging
import os
from os import environ as env
import shlex
import subprocess
import sys

import piecash
from piecash import Transaction, Split, GnucashException

'''This is the helper library for the main web app'''


def configure_logging():
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
    '''Get the environment variable `name` from environment variable.
       Return the value of the `name` env var if found, None otherwise.'''
    try:
        env_var = env[name]
    except KeyError as ke:
        logger.critical(f'Could not get env. var. "{ke}". Make sure it is set')
    else:
        return env_var


def get_book_name_from_env():
    '''Get the GnuCash book name from an environment variable'''
    try:
        book_name = env['GNUCASH_BOOK_NAME']
    except KeyError as ke:
        logger.critical(f'Could not get GnuCash book name from env. var. {ke}.')
        sys.exit(1)
    else:
        return book_name


def open_book(book_name, readonly=False, open_if_lock=True, do_backup=False):
    '''Open a GnuCash book for reading and potentially writing'''
    try:
        book = piecash.open_book(book_name, readonly=readonly, open_if_lock=open_if_lock, do_backup=do_backup)
    except GnucashException as gce:
        logger.critical(f'Error while attempting to open GnuCash book "{book_name}"')
        logger.critical(gce)
        sys.exit(1)
    else:
        return book


def list_accounts(book):
    '''List accounts in an existing book.
       `book` should be the fully qualified path to the GnuCash book.'''
    book = open_book(book, readonly=True)
    accounts = sorted([x.fullname for x in book.accounts])
    book.close()

    return accounts


def get_account(account_name, book):
    '''Return a piecash Account object that matches `account_name`,
       or return None if no match is found.'''
    accounts = book.accounts
    search_name = account_name.lower()
    for account in accounts:
        if account.fullname.lower() == search_name:
            return account

    return None


def add_account(book, new_acct_name, parent, currency='USD'):
    '''Add a GnuCash account with name `new_acct_name` and a parent account of `parent`.
    Optionally set USD'''
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
    '''Return the last `n` transactions from the GnuCash book `book`.
       The transactions are returned as a dict where the items are:
           source: source account name
           dest: destination account name
           date: the enter date of the transaction (e.g. 2021-01-01)
           amount: the amount of money'''
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
    '''Add a transaction to an existing book.
       `amount` should be a float out to 2 decimal places for the value of the transaction.
       `debit_acct` and `credit_acct` should be the names of the accounts as given by the .fullname
           method from a GnuCash Account, e.g. book.accounts.get(fullname="Expenses:Food")'''
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


def create_recursive_acct_tree(tree, deq):
    '''Given a deque of accounts such as 'Accounts:Checking:Food' and a
       Treelib.Tree object, recursively iterate over each element of the deque
       adding it as a child of the previous leaf object of the tree.

       Note: I still need to figure out how to graft trees like this together!

       example:
       tree = Tree()
       tree.create_node('Accounts', 'accounts')
       deq = deque('Assets:Checking:Food'.split(':'))
       t = create_recursive_acct_tree(tree, deq)
       t.show()

       Accounts
       └── Assets
           └── Personal Checking
               └── Budget
                   └── Credit Cards and Loans
       '''
    parent = tree.leaves()[0].identifier
    logger.debug(f'The parent is: {parent}')
    logger.debug(f'Creating node with deq == {deq}')
    tree.create_node(deq[0], deq[0].lower(), parent=parent)
    if len(deq) == 1:
        return tree
    else:
        logger.debug('Running popleft()')
        deq.popleft()
        logger.debug(f'Running recursion with deq == {deq}')
        return create_recursive_acct_tree(tree, deq)


def get_gnucash_dir():
    '''Get the fully qualified path of the directory of your .gnucash file'''
    try:
        gnucash_dir = env['GNUCASH_DIR']
    except KeyError as ke:
        logger.critical(f'Error, could not get GnuCash directory {ke} from env var')
        logger.critical('Make sure to set $GNUCASH_DIR')
        sys.exit(1)
    else:
        return gnucash_dir


def get_git_user_name_and_email_from_env():
    '''Get the git user's name and email address from environment variables.
       Note: these are NOT the _GitHub_ username and email, necessarily. Rather,
       these are used for git commit messages for attribution's sake.'''
    try:
        git_user = env['GIT_USER']
        git_email = env['GIT_EMAIL']
    except KeyError as ke:
        logger.critical(f'Failed to source {ke} from env var. Make sure to set it')
        sys.exit(1)
    else:
        return (git_user, git_email)


def get_github_token_and_url_from_env():
    '''Get the user's GitHub Personal Access Token and repo URL from
       environment variables.'''
    try:
        gh_token = env['GITHUB_TOKEN']
        gh_url = env['GITHUB_GNUCASH_URL']
    except KeyError as ke:
        logger.critical(f'Failed to source env var {ke}. Ensure it is set')
        sys.exit(1)
    else:
        return (gh_token, gh_url)


def run_shell_command(command_str):
    '''Run a shell comand using subprocess.run. Return completed command obj'''
    command = shlex.split(command_str)
    run = subprocess.run(command, capture_output=True)

    return run


def git_set_user_and_email(username, email):
    '''Set the git global config user's name, e.g. "Brenden Hyde" and
       email address. This is used by git when writing commit messages
       for attribution.'''
    user_cmd = f'git config --global user.name {username}'
    email_cmd = f'git config --global user.email {email}'

    user_run = run_shell_command(user_cmd)
    email_run = run_shell_command(email_cmd)
    if user_run.returncode == 0 and email_run.returncode == 0:
        logger.info('Successfully configured git user\'s name and email')
        return True
    elif user_run.returncode == 0 and email_run.returncode != 0:
        logger.error('Git global config set for user\'s name but not email')
        return False
    elif user_run.returncode != 0 and email_run.returncode == 0:
        logger.error('Git global config set for user\'s email but not name')
        return False
    else:
        logger.error('Git global config of user\'s name and email is messed up!')
        return False


def git_ensure_cloned(gnucash_dir, gh_token, gh_url):
    '''Ensure the gnucash git repo is already present, and clone it if not.
       The `gh_url` var should be an HTTPS URL to your GnuCash GitHub repo.
       The `gh_token` var is a Personal Access Token from GitHub.'''
    logger.info('Checking whether the GnuCash GitHub repo was already cloned')
    repo_exists = os.path.exists(gnucash_dir)
    if repo_exists:
        logger.info('GnuCash GitHub repository folder exists. Not cloning.')
        return True
    else:
        clone_url = gh_url.replace('https://', f'https://{gh_token}@')
        logger.info('Cloning GnuCash GitHub repo from URL:')
        logger.info('{clone_url}')
        cmd = f'git clone {clone_url}'
        logger.info('Running `git clone` with the following command:')
        logger.info(cmd)
        run = run_shell_command(cmd)

        if run.returncode == 0:
            logger.info('Successfully cloned the GnuCash GitHub repo.')
            return True
        else:
            logger.error('Failed to clone the GnuCash GitHub repo:')
            logger.error(run)
            return False


def git_check_uncommitted(gnucash_dir):
    '''Run `git status` in the context of the GnuCash directory to check for
       uncommitted changes. If there are uncommitted changes, return True.
       Otherwise, return False if there are no changes to the git repo.'''
    cmd = f'git -C {gnucash_dir} status'
    run = run_shell_command(cmd)

    changed_str = 'Changes not staged for commit:'
    stdout = run.stdout.decode('utf-8')
    logger.info('Checking for uncommitted changes to the GnuCash git repo.')

    if changed_str in stdout:
        logger.warning('There are uncommitted changes in the GnuCash git repo.')
        return True
    else:
        logger.info('There were no uncommitted changes to the GnuCash git repo.')
        return False


def git_ensure_discard_uncommitted(gnucash_dir, book_name):
    '''Run `git checkout` against the GnuCash file to discard any uncommitted
       changes. This needs to be done because even just OPENING a GnuCash
       book, making no changes, and closing it results in a modified file.
       This, in turn, makes `git pull` break because it can't merge.'''
    uncommitted_changes = git_check_uncommitted(gnucash_dir)

    if uncommitted_changes:
        cmd = f'git -C "{gnucash_dir}" checkout "{book_name}"'
        logger.info('Running `git checkout` to discard uncommitted changes')
        logger.info(cmd)
        run = run_shell_command(cmd)

        if run.returncode == 0:
            logger.info(f'Successfully ran "{cmd}" to clear uncommitted changes')
        else:
            logger.critical(f'Failed while running command {cmd} to clear changes:')
            logger.critical(run)
            sys.exit(1)


def git_pull(gnucash_dir):
    '''Run a `git pull` command in the directory with the GnuCash book.'''
    cmd = f'git -C {gnucash_dir} pull'
    logger.info('Running `git pull` with the following command:')
    logger.info(cmd)
    run = run_shell_command(cmd)

    if run.returncode == 0:
        logger.info('successfully ran `git pull`')
        return True
    else:
        logger.critical('Failed to run a `git pull` command.\
                See below for command output')
        logger.critical(run)
        return False


def git_add(gnucash_dir, gnucash_book):
    '''Run `git add {gnucash_book}` in the context of the GnuCash book directory.
       `gnucash_dir` should be a fully qualified path to your GnuCash dir'''
    cmd = f'git -C "{gnucash_dir}" add "{gnucash_book}"'
    logger.info('Running `git add` with the following command:')
    logger.info(cmd)
    run = run_shell_command(cmd)

    if run.returncode == 0:
        logger.info(f'Successfully ran `git add {gnucash_book}` in GnuCash directory')
        return True
    else:
        logger.critical('Failed to run a `git add` command.\
                  See below for command output')
        logger.critical(run)
        return False


def git_commit(gnucash_dir, message):
    '''Run `git commit -m "{message}"` in the context of the GnuCash dir'''
    cmd = f'git -C {gnucash_dir} commit -m "{message}"'
    logger.info('Running `git commit` with the following command:')
    logger.info(cmd)
    run = run_shell_command(cmd)

    if run.returncode == 0:
        logger.info('Successfully ran the following git commit command:')
        logger.info(cmd)
        return True
    else:
        logger.error('Failed to run a `git commit` command.\
                  See below for command output')
        logger.error(run)
        return False


def git_push(gnucash_dir):
    '''Run a `git push` command in the context of the GnuCash directory'''
    cmd = f'git -C {gnucash_dir} push'
    logger.info('Running `git push` with the following command:')
    logger.info(cmd)
    run = run_shell_command(cmd)

    if run.returncode == 0:
        logger.info('Successfully ran `git push`')
        return True
    else:
        logger.error('Failed to run `git push`.\
                See below for command output')
        print(run)
        return False


def git_add_commit_and_push(gnucash_dir, gnucash_book, commit_message):
    '''Run `git add .`, `git commit -m "message"`, and `git push`,
       all in the context of the directory that contains your GnuCash file.'''
    added = git_add(gnucash_dir, gnucash_book)
    if added:
        committed = git_commit(gnucash_dir, commit_message)
        if committed:
            pushed = git_push(gnucash_dir)
            if pushed:
                return (True, None)
            else:
                failure = 'Git add and commit succeeded, but pushing failed'
                logger.critical(failure)
                return (False, failure)
        else:
            failure = 'Git add succeeded, but commit failed. Did not try a push'
            logger.critical(failure)
            return (False, failure)
    else:
        failure = 'Git add failed'
        logger.critical(failure)
        return (False, failure)
