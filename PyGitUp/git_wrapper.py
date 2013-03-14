# coding=utf-8
"""
A wrapper extending GitPython's repo.git.

This wrapper class provides support for stdout messages in Git Exceptions
and (nearly) realtime stdout output. In addition, some methods of the
original repo.git are shadowed by custom methods providing functionality
needed for `git up`.
"""

from __future__ import print_function

__version__ = 0.1
__all__ = ['GitWrapper', 'GitError']

###############################################################################
# IMPORTS
###############################################################################

# Python libs
import sys
import re
from contextlib import contextmanager

# 3rd party libs
from termcolor import colored  # Assume, colorama is already initialized
from git import GitCommandError, CheckoutError

# PyGitUp libs
from PyGitUp.utils import find


###############################################################################
# GitWrapper
###############################################################################

class GitWrapper():
    """
    A wrapper for repo.git providing better stdout handling + better exeptions.

    It is preferred to repo.git because it doesn't print to stdout
    in real time. In addition, this wrapper provides better error
    handling (it provides stdout messages inside the exception, too).
    """

    def __init__(self, repo):
        self.repo = repo
        self.git = self.repo.git

    def run(self, name, *args, **kwargs):
        """ Run a git command specified by name and args/kwargs. """

        tostdout = kwargs.pop('tostdout', False)
        stdout = ''

        # Execute command
        cmd = getattr(self.git, name)(as_process=True, *args, **kwargs)

        # Capture output
        while True:
            output = cmd.stdout.read(4)

            # Print to stdout
            if tostdout:
                sys.stdout.write(output)
                sys.stdout.flush()

            stdout += output

            if output == "":
                break

        # Wait for the process to quit
        try:
            cmd.wait()
        except GitCommandError as error:
            # Add more meta-information to errors
            message = "'{0}' returned exit status {1}".format(
                error.command,
                error.status
            )

            raise GitError(error.stderr, stdout, message)

        return stdout.strip()

    def __getattr__(self, name):
        return lambda *args, **kwargs: self.run(name, *args, **kwargs)

    ###########################################################################
    # Overwrite some methods and add new ones
    ###########################################################################

    @contextmanager
    def stash(self):
        """
        A stashing contextmanager.
        It  stashes all changes inside and unstashed when done.
        """
        stashed = False

        if self.repo.is_dirty():
            print(colored(
                'stashing {0} changes'.format(self.change_count),
                'magenta'
            ))
            self.git.stash()
            stashed = True

        yield

        if stashed:
            print(colored('unstashing', 'magenta'))
            try:
                self.git.stash('pop')
            except GitCommandError as e:
                error = GitError()
                error.message = "Failed unstash"
                error.stdout = e.stdout
                error.stderr = e.stderr

                raise error

    def remote_ref_for_branch(self, branch):
        """ Get the remote reference for a local branch. """

        # Get name of the remote containing the branch
        remote_name = (self.config('branch.{0}.remote'.format(branch.name)) or
                       'origin')

        # Get name of the remote branch
        remote_branch = (self.config('branch.{0}.merge'.format(branch.name)) or
                         branch.name)
        remote_branch = remote_branch.split('refs/heads/').pop()

        # Search the remote reference
        remote = find(
            self.repo.remotes,
            lambda remote: remote.name == remote_name
        )
        return find(
            remote.refs,
            lambda ref: ref.name == "{0}/{1}".format(remote_name, remote_branch)
        )

    @property
    def change_count(self):
        """ The number of changes in the working directory. """
        return len(
            self.git.status(porcelain=True, untracked_files='no').split('\n')
        )

    def checkout(self, branch_name):
        """ Checkout a branch by name. """
        try:
            (find(self.repo.branches, lambda b: b.name == branch_name)
                .checkout())
        except CheckoutError as e:
            error = GitError()
            error.message = "Failed to checkout " + branch_name
            error.details = e

            raise error

    def rebase(self, target_branch):
        """ Rebase to target branch. """
        current_branch = self.repo.active_branch

        arguments = (
            (self.config('rebase.arguments') or []) + [target_branch.name]
        )
        try:
            self.git.rebase(*arguments)
        except GitError as error:
            error.message = "Failed to rebase {0} onto {1]".format(
                current_branch.name, target_branch.name
            )
            raise error

    def config(self, key):
        """ Return `git config key` output or None. """
        try:
            return self.git.config(key)
        except GitCommandError:
            return None

    def version(self):
        """
        Return git's version as a list of numbers.

        The original repo.git.version_info has problems with tome types of
        git version strings.
        """
        return re.search(r'\d+(\.\d+)+', self.git.version()).group(0)

    def is_version_min(self, required_version):
        """ Does git's version match the requirements? """
        return self.version().split('.') >= required_version.split('.')


###############################################################################
# GitError
###############################################################################

class GitError(GitCommandError):
    """
    Extension of the GitCommandError class.

    New:
    - stdout
    - details: a 'nested' exception with more details)
    """

    def __init__(self, stderr=None, stdout=None, details=None, message=None):
        super(GitError, self).__init__(None, None, stderr)
        self.stdout = stdout
        self.details = details
        self.message = message