# Git Commands for Branch Management

Here are the commands used to manage your Git branches, along with explanations:

```bash
git status
```
This command shows the current state of your working directory and the staging area. It lets you see which changes have been staged, which haven't, and which files aren't being tracked by Git.

```bash
git add .
```
This command stages all changes in the current directory and its subdirectories. This means that all new, modified, and deleted files will be included in the next commit.

```bash
git commit -m "feat: new features and bug fixes"
```
This command records the staged changes to the repository with a descriptive message. The `-m` flag allows you to provide the commit message directly in the command.

```bash
git checkout -b dev
```
This command does two things:
1.  `git branch dev`: Creates a new branch named `dev`.
2.  `git checkout dev`: Switches your working directory to the newly created `dev` branch.

```bash
git push -u origin dev
```
This command pushes the `dev` branch from your local repository to the `origin` (remote) repository. The `-u` flag sets the `dev` branch on the remote as the upstream branch for your local `dev` branch, meaning future `git push` and `git pull` commands will automatically know which remote branch to interact with.