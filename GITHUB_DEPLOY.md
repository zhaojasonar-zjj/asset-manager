# GitHub 部署指南

本文档介绍如何将项目部署到 GitHub，并通过 Streamlit Community Cloud 实现免费公网访问。

---

## 方式一：一键脚本部署（推荐）

### 第 1 步：生成 GitHub Token

1. 登录 GitHub → 点击右上角头像 → **Settings**
2. 左侧栏最底部 → **Developer settings**
3. **Personal access tokens** → **Tokens (classic)**
4. 点击 **Generate new token (classic)**
5. Note 填 `stock-portfolio`，Expiration 选 `90 days`
6. 勾选 **repo** （全部子项）
7. 点击 **Generate token** → 复制 token（`ghp_` 开头）

### 第 2 步：运行部署脚本

```bash
cd stock-portfolio
chmod +x deploy.sh
./deploy.sh
```

按提示输入：
- GitHub 用户名
- 刚才复制的 Token
- 仓库名称（默认 `stock-portfolio`，回车即可）

脚本会自动：创建远程仓库 → 推送代码 → 输出部署链接。

### 第 3 步：部署到 Streamlit Cloud

1. 访问 [share.streamlit.io](https://share.streamlit.io)
2. 用 GitHub 账号登录
3. 点击 **New app**
4. 选择仓库：`你的用户名/stock-portfolio`
5. 主文件路径填：`app.py`
6. 点击 **Deploy!**

部署完成后获得公网地址，如 `https://你的用户名-stock-portfolio.streamlit.app`

---

## 方式二：手动命令行部署

```bash
# 1. 在 GitHub 网页上创建空仓库 stock-portfolio（不要勾选 README）

# 2. 本地初始化并推送
cd stock-portfolio
git init
git add -A
git commit -m "Initial commit: 个人股票资产管理系统"

git remote add origin https://github.com/你的用户名/stock-portfolio.git
git branch -M main
git push -u origin main
```

---

## 方式三：GitHub Desktop（图形界面）

1. 下载 [GitHub Desktop](https://desktop.github.com/)
2. File → Add Local Repository → 选择 `stock-portfolio` 文件夹
3. 如果提示 "This directory does not appear to be a Git repository"，点击 **create a repository**
4. 填写仓库名称 → 点击 **Create repository**
5. 点击 **Publish repository** → 取消勾选 "Keep this code private"（如果想公开）
6. 点击 **Publish repository**

---

## Streamlit Cloud 部署详解

### 前提条件
- GitHub 仓库已创建且代码已推送
- 仓库根目录有 `requirements.txt` 和 `app.py`

### 部署步骤

1. 访问 [share.streamlit.io](https://share.streamlit.io)
2. 用 GitHub 登录
3. **New app** → 填写：

| 配置项 | 值 |
|--------|------|
| Repository | `你的用户名/stock-portfolio` |
| Branch | `main`（或 `master`）|
| Main file path | `app.py` |
| Python version | 3.12（默认）|

4. **Advanced settings**（可选）：
   - 如果需要密钥等环境变量，在 Secrets 中添加
5. 点击 **Deploy!**

### 部署后

- 应用获得公网地址：`https://你的用户名-stock-portfolio.streamlit.app`
- 免费额度：每月 1000 小时运行时间
- 仓库代码更新后，Streamlit Cloud 自动重新部署

---

## 本地运行

```bash
cd stock-portfolio
pip install -r requirements.txt
streamlit run app.py
```

浏览器访问 `http://localhost:8501`

---

## 常见问题

### Q: 推送时提示 "Authentication failed"
**A:** Token 过期或权限不足。确保生成 Token 时勾选了 `repo` 权限。2021 年后 GitHub 不再支持密码认证，必须用 Token。

### Q: Streamlit Cloud 部署后页面报错
**A:** 检查 `requirements.txt` 是否完整，确保所有依赖都已列出。

### Q: 腾讯财经接口在云端访问不了
**A:** Streamlit Cloud 服务器在海外，部分国内接口可能延迟较高但通常可访问。如需备用方案，可替换为新浪财经接口。

### Q: 如何更新代码
**A:**
```bash
git add -A
git commit -m "update: 描述修改内容"
git push
```
推送后 Streamlit Cloud 自动重新部署。

### Q: 如何设为私有仓库
**A:** GitHub 创建仓库时勾选 "Private"。Streamlit Cloud 免费版要求仓库为公开，私有仓库需升级 Streamlit Cloud 付费版。
