# 🚀 How to Push SongSense to GitHub

## Prerequisites
- GitHub account with username: `tb-shreya-singh`
- Git configured locally (✅ Already done)
- Repository code committed locally (✅ Already done)

## Step-by-Step Instructions

### Step 1: Create the Repository on GitHub

1. Open your browser and go to: **https://github.com/new**
2. Log in to GitHub with your account: `tb-shreya-singh`
3. Fill in the repository details:
   - **Repository name**: `SongSense`
   - **Description** (optional): "Shazam-like song identification with audio fingerprinting and pixel-art UI"
   - **Visibility**: Choose `Public` (recommended for portfolios) or `Private`
   - **Initialize this repository with**: **LEAVE UNCHECKED** (don't add README, .gitignore, or license)
4. Click **"Create repository"**

### Step 2: Push Your Code

After creating the repository, GitHub will show you a quick setup guide. Run this command in your terminal:

```bash
cd "c:\Users\Shreya\OneDrive\Desktop\SongSense"
git push -u origin main
```

GitHub will prompt you for authentication:
- **Username**: Your GitHub username
- **Password/Token**: Use a Personal Access Token (see troubleshooting below)

### Step 3: Verify Your Repository

1. Go to: **https://github.com/tb-shreya-singh/SongSense**
2. You should see all your files:
   - ✅ app.py
   - ✅ fingerprint.py
   - ✅ templates/index.html
   - ✅ requirements.txt
   - ✅ README.md
   - ✅ And 13+ more files

## Troubleshooting

### "fatal: repository not found"
- Verify the repository exists at https://github.com/tb-shreya-singh/SongSense
- Check that you created it on the correct GitHub account
- Ensure you didn't check any "Initialize repository" options

### "fatal: Authentication failed"
GitHub deprecated password authentication in 2021. Use a Personal Access Token instead:

1. Go to: https://github.com/settings/tokens
2. Click **"Generate new token"** (classic)
3. Give it a name: "SongSense"
4. Select scopes: `repo` (full control of private repositories)
5. Click **"Generate token"**
6. Copy the token
7. When Git prompts for password, paste the token

### Connection error on Windows
If you get SSL certificate errors:

```bash
git config --global http.sslVerify false
git push -u origin main
```

### Still having issues?
Try using SSH instead of HTTPS:

```bash
# Change remote to SSH
git remote set-url origin git@github.com:tb-shreya-singh/SongSense.git

# Push with SSH
git push -u origin main
```

## What Gets Pushed

✅ **Committed to Git**:
- All source code files
- Configuration files
- UI templates
- Documentation (README, DEPLOY, PROJECT_STATUS)
- .gitignore to exclude venv, database, etc.

❌ **NOT Pushed** (excluded by .gitignore):
- `.venv/` directory (Python virtual environment)
- `fingerprints.db` (SQLite database)
- `uploads/` (temporary uploaded files)
- `songs/*.mp3` (audio files - too large)
- Python cache files (`__pycache__/`, `*.pyc`)

## After Pushing

Great! Your repository is now on GitHub. Next steps:
- ⭐ Star your own repository (optional)
- 📝 Add to your portfolio
- 🔗 Share the GitHub link: https://github.com/tb-shreya-singh/SongSense
- 📊 Check GitHub insights to see commit activity
- 🤝 Consider enabling "Discussions" for collaboration

## Commands Reference

```bash
# View git configuration
git config --list

# Check remote URL
git remote -v

# View commit history
git log --oneline -10

# View uncommitted changes
git status

# Push again if you make changes
git add .
git commit -m "Your commit message"
git push origin main
```

---

**When you're ready, run:**
```
git push -u origin main
```

Good luck! 🎵
