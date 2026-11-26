#!/bin/bash
# Publica uma versão: confere que tudo diz a mesma versão, que a main está limpa,
# em dia e com os testes verdes, e envia a tag v<versão>. O workflow "Android app"
# compila o APK e cria a release dessa tag.
#
#   tools/release.sh            # usa a versão de bsmd/__init__.py
#   tools/release.sh --dry-run  # só confere
set -euo pipefail
cd "$(dirname "$0")/.."

dry=0
[ "${1:-}" = "--dry-run" ] && dry=1

version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' usr/share/big-screen-monitor-display/bsmd/__init__.py)
tag="v$version"
die() { echo "release: $*" >&2; exit 1; }

[ -n "$version" ] || die "versão não encontrada em bsmd/__init__.py"
python3 -m pytest -q tests/test_version.py >/dev/null || die "versões divergentes (rode pytest tests/test_version.py)"
grep -q "^## \[$version\]" CHANGELOG.md 2>/dev/null || die "CHANGELOG.md sem a seção ## [$version]"

[ "$(git branch --show-current)" = "main" ] || die "rode na branch main"
[ -z "$(git status --porcelain)" ] || die "há mudanças não commitadas"
git fetch -q origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || die "a main local difere da origin/main"
git rev-parse -q --verify "refs/tags/$tag" >/dev/null && die "a tag $tag já existe"
git ls-remote --exit-code --tags origin "$tag" >/dev/null 2>&1 && die "a tag $tag já existe no GitHub"

# O CI precisa estar verde neste commit: sem o gh não há como conferir, então para.
command -v gh >/dev/null || die "o gh (GitHub CLI) é necessário para conferir o workflow Tests"
sha=$(git rev-parse HEAD)
# The REST API filtered by head_sha (``gh run list --commit`` returned nothing here
# even with a green run, which blocked every release).
repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
state=$(gh api "repos/$repo/actions/runs?head_sha=$sha&event=push" \
        --jq '[.workflow_runs[] | select(.name == "Tests")][0].conclusion // empty' 2>/dev/null || true)
[ "$state" = "success" ] || die "o workflow Tests deste commit não está verde (estado: ${state:-sem execução})"

echo "release: $tag pronta ($(git rev-parse --short HEAD))"
[ "$dry" = 1 ] && exit 0
git tag -a "$tag" -m "Big Screen Monitor Display $version"
git push origin "$tag"
echo "release: tag enviada; o APK e a release saem do workflow \"Android app\""
