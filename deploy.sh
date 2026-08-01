#!/bin/bash
# ============================================
#  一键部署到 GitHub + Streamlit Cloud
# ============================================
#
# 使用方法:
#   1. 在 GitHub 创建 Personal Access Token:
#      Settings → Developer settings → Personal access tokens → Tokens (classic)
#      勾选 repo 权限，生成后复制 token
#
#   2. 运行此脚本:
#      chmod +x deploy.sh
#      ./deploy.sh
#
#   3. 按提示输入 GitHub 用户名和 Token
#
#   4. 前往 https://share.streamlit.io 部署
# ============================================

set -e

echo "========================================"
echo "  个人股票资产管理系统 — GitHub 部署"
echo "========================================"
echo ""

# 检查 git
if ! command -v git &> /dev/null; then
    echo "❌ 未安装 git，请先安装: sudo apt install git"
    exit 1
fi

# 输入 GitHub 信息
read -p "GitHub 用户名: " GH_USER
read -sp "GitHub Personal Access Token: " GH_TOKEN
echo ""
read -p "仓库名称 (默认: stock-portfolio): " REPO_NAME
REPO_NAME=${REPO_NAME:-stock-portfolio}

echo ""
echo "→ 正在创建 GitHub 仓库..."

# 创建远程仓库
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
    -H "Authorization: token $GH_TOKEN" \
    -H "Accept: application/vnd.github.v3+json" \
    https://api.github.com/user/repos \
    -d "{\"name\":\"$REPO_NAME\",\"description\":\"基于 Streamlit 的个人股票资产管理系统\",\"private\":false}")

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

if [ "$HTTP_CODE" = "201" ]; then
    echo "✓ 仓库创建成功: https://github.com/$GH_USER/$REPO_NAME"
elif [ "$HTTP_CODE" = "422" ]; then
    echo "⚠ 仓库已存在，将推送到现有仓库"
else
    echo "❌ 创建仓库失败 (HTTP $HTTP_CODE)"
    echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message','unknown'))" 2>/dev/null
    exit 1
fi

# 配置远程地址
git remote remove origin 2>/dev/null || true
git remote add origin "https://$GH_USER:$GH_TOKEN@github.com/$GH_USER/$REPO_NAME.git"

echo "→ 推送代码到 GitHub..."
git push -u origin master 2>&1 | sed "s/$GH_TOKEN/***token***/g"

echo ""
echo "========================================"
echo "  ✅ 代码已推送到 GitHub"
echo "========================================"
echo ""
echo "  仓库地址: https://github.com/$GH_USER/$REPO_NAME"
echo ""
echo "→ 下一步: 部署到 Streamlit Community Cloud"
echo "  1. 访问 https://share.streamlit.io"
echo "  2. 用 GitHub 账号登录"
echo "  3. 点击 'New app'"
echo "  4. 选择仓库: $GH_USER/$REPO_NAME"
echo "  5. 主文件路径: app.py"
echo "  6. 点击 'Deploy!' 即可"
echo ""
echo "  部署后获得公网访问地址，免费使用"
echo "========================================"
