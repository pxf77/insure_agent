#!/usr/bin/env bash
set -euo pipefail

readonly CHOICE_SDK_VERSION="2.7.5.0"
readonly CHOICE_SDK_URL="https://cftdlcdn.eastmoney.com/Choice/EMQuantAPI/EMQuantAPI_Python.zip"
readonly CHOICE_SDK_SHA256="397d00615b0baabf82379394d0ba5ccdc7fe16a048b292c75d91bbb87149239b"

usage() {
  cat <<'EOF'
Usage:
  scripts/install_choice_sdk.sh <absolute-destination> <python> [sdk-archive]

Examples:
  scripts/install_choice_sdk.sh \
    /opt/insure-agent/vendor/choice/2.7.5.0 \
    /opt/insure-agent/.venv/bin/python

  scripts/install_choice_sdk.sh \
    /opt/insure-agent/vendor/choice/2.7.5.0 \
    /opt/insure-agent/.venv/bin/python \
    /tmp/EMQuantAPI_Python.zip

The optional archive must be the official Choice Python V2.7.5.0 package. The
installer verifies its pinned SHA-256 before extracting or executing anything.
EOF
}

if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 2 || $# -gt 3 ]]; then
  usage >&2
  exit 2
fi

readonly destination=$1
readonly python_bin=$2
readonly supplied_archive=${3:-}

if [[ $destination != /* || $destination == "/" ]]; then
  echo "destination must be an absolute, non-root path" >&2
  exit 2
fi
if [[ ! -x $python_bin ]]; then
  echo "python executable is unavailable: $python_bin" >&2
  exit 2
fi
if [[ -e $destination ]]; then
  echo "destination already exists; refusing to overwrite: $destination" >&2
  exit 2
fi
if [[ $(uname -s) != "Linux" ]]; then
  echo "this installer supports Linux hosts only" >&2
  exit 2
fi
if ! "$python_bin" -c 'import sys; raise SystemExit(not ((3, 10) <= sys.version_info[:2] < (3, 14)))'; then
  echo "python must satisfy >=3.10,<3.14" >&2
  exit 2
fi
for executable in sha256sum unzip; do
  if ! command -v "$executable" >/dev/null 2>&1; then
    echo "required executable is unavailable: $executable" >&2
    exit 2
  fi
done
if [[ -z $supplied_archive ]] && ! command -v curl >/dev/null 2>&1; then
  echo "curl is required when no local SDK archive is supplied" >&2
  exit 2
fi

readonly temporary_root=$(mktemp -d /tmp/choice-sdk-install.XXXXXX)
staging_directory=""
cleanup() {
  rm -rf -- "$temporary_root"
  if [[ -n $staging_directory && -d $staging_directory ]]; then
    rm -rf -- "$staging_directory"
  fi
}
trap cleanup EXIT

readonly archive="$temporary_root/EMQuantAPI_Python.zip"
if [[ -n $supplied_archive ]]; then
  if [[ ! -f $supplied_archive || -L $supplied_archive ]]; then
    echo "SDK archive must be a regular non-symlink file" >&2
    exit 2
  fi
  cp -- "$supplied_archive" "$archive"
else
  curl \
    --fail \
    --location \
    --retry 3 \
    --retry-all-errors \
    --connect-timeout 10 \
    --output "$archive" \
    "$CHOICE_SDK_URL"
fi

echo "$CHOICE_SDK_SHA256  $archive" | sha256sum --check --status
unzip -q "$archive" -d "$temporary_root/extracted"

readonly source_directory="$temporary_root/extracted/EMQuantAPI_Python/python3"
case $(uname -m) in
  x86_64 | amd64)
    readonly platform_library="$source_directory/libs/linux/x64/libEMQuantAPIx64.so"
    ;;
  aarch64 | arm64)
    readonly platform_library="$source_directory/libs/linuxArm/x64/libEMQuantAPIx64.so"
    ;;
  *)
    echo "unsupported Linux architecture: $(uname -m)" >&2
    exit 2
    ;;
esac
for required_path in \
  "$source_directory/EmQuantAPI.py" \
  "$source_directory/installEmQuantAPI.py" \
  "$platform_library"; do
  if [[ ! -f $required_path || -L $required_path ]]; then
    echo "official SDK package is incomplete or unsafe: $required_path" >&2
    exit 1
  fi
done

readonly destination_parent=$(dirname "$destination")
mkdir -p -- "$destination_parent"
staging_directory=$(mktemp -d "$destination_parent/.choice-sdk.XXXXXX")
cp -a -- "$source_directory/." "$staging_directory/"
chmod -R go-rwx "$staging_directory"
mv -- "$staging_directory" "$destination"
staging_directory=""

"$python_bin" "$destination/installEmQuantAPI.py"
"$python_bin" -c "from EmQuantAPI import c; print('Choice SDK import: OK')"

echo "Choice SDK V$CHOICE_SDK_VERSION installed at $destination"
echo "Activation is still required; do not place credentials or userInfo in Git."
