#!/bin/bash
export GIT_AUTHOR_NAME="oyukinon"
export GIT_AUTHOR_EMAIL="yukinon163@gmail.com"
export GIT_COMMITTER_NAME="oyukinon"
export GIT_COMMITTER_EMAIL="yukinon163@gmail.com"

# 获取需要修改的 commit 列表
for commit in $(git log --format="%H" --all); do
    name=$(git log -1 --format="%an" $commit)
    if [ "$name" = "s2my6hvsvc-beep" ]; then
        echo "Fixing $commit"
    fi
done
