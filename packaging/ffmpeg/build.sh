#!/bin/sh
# Build the ffmpeg.exe the video extension package carries: an LGPL-2.1-or-later ffmpeg for
# 64-bit Windows, cross-compiled with mingw-w64, holding only what the video helper uses
# (src/solidseas_app/extensions/video_helper.py): PNG frames in through image2, GIF out
# through the palette filters, MP4 out through Windows' own H.264 encoder (h264_mf) or
# MPEG-4 part 2. No GPL, no nonfree and no external codec library (no OpenH264), and no
# DLLs beside it: zlib and the mingw runtime are linked in.
#
# Run it in a clean Debian 13 (trixie) container, from the repository root:
#
#   docker run --rm -e OWNER="$(id -u):$(id -g)" -v "$PWD/packaging/ffmpeg:/build" debian:trixie sh /build/build.sh
#
# It builds in the container's /tmp and hands what it writes to OWNER.
# It writes into packaging/ffmpeg/out/ (gitignored): ffmpeg.exe, the source tarball it was
# built from with FFmpeg's signature, the licence texts, and BUILD.txt (versions, configure
# flags, checksums). The source tarball and this script are the exact source the LGPL asks
# for; publish both beside the package (THIRD_PARTY_NOTICES.txt section 3).
set -eu

FFMPEG_VERSION=9.0.2
# FFmpeg's release signing key (ffmpeg-devel@ffmpeg.org), as published at https://ffmpeg.org/ffmpeg-devel.asc
FFMPEG_KEY=FCF986EA15E6E293A5644F10B4322F04D67658D8

apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    ca-certificates curl gnupg xz-utils make nasm pkg-config gcc libc6-dev \
    gcc-mingw-w64-x86-64-posix binutils-mingw-w64-x86-64 mingw-w64-x86-64-dev libz-mingw-w64-dev >/dev/null

OUT=/build/out
rm -rf "$OUT" && mkdir -p "$OUT"
cd /tmp
curl -fsSLO "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz"
curl -fsSLO "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz.asc"
curl -fsSL https://ffmpeg.org/ffmpeg-devel.asc | gpg --batch --quiet --import
gpg --batch --status-fd 1 --verify "ffmpeg-$FFMPEG_VERSION.tar.xz.asc" "ffmpeg-$FFMPEG_VERSION.tar.xz" 2>/dev/null \
    | grep -q "VALIDSIG $FFMPEG_KEY" || { echo "the source tarball's signature is not FFmpeg's" >&2; exit 1; }
tar xJf "ffmpeg-$FFMPEG_VERSION.tar.xz"
cd "ffmpeg-$FFMPEG_VERSION"

FLAGS="--target-os=mingw32 --arch=x86_64 --cross-prefix=x86_64-w64-mingw32- --pkg-config=pkg-config
 --prefix=/opt/ffmpeg --enable-static --disable-shared --extra-ldflags=-static
 --disable-autodetect --disable-everything --disable-network --disable-doc --disable-debug
 --disable-ffplay --disable-ffprobe --enable-w32threads --enable-zlib --enable-mediafoundation --enable-d3d11va
 --enable-swscale --enable-protocol=file --enable-demuxer=image2 --enable-decoder=png --enable-parser=png
 --enable-encoder=gif,mpeg4,h264_mf --enable-muxer=gif,mp4
 --enable-filter=split,palettegen,paletteuse,scale,format,null"
# shellcheck disable=SC2086
./configure $FLAGS >/tmp/configure.log 2>&1 || { tail -30 ffbuild/config.log >&2; exit 1; }
make -j"$(nproc)" >/tmp/make.log 2>&1 || { tail -40 /tmp/make.log >&2; exit 1; }
x86_64-w64-mingw32-strip ffmpeg.exe

# Licence files at the top of the folder, named as scripts/build-extensions.ps1 picks them up.
cp ffmpeg.exe "$OUT/"
cp "../ffmpeg-$FFMPEG_VERSION.tar.xz" "../ffmpeg-$FFMPEG_VERSION.tar.xz.asc" "$OUT/"
cp COPYING.LGPLv2.1 "$OUT/COPYING.LGPLv2.1.txt"
cp LICENSE.md "$OUT/LICENSE-ffmpeg.md"
cp /usr/share/doc/libz-mingw-w64-dev/copyright "$OUT/LICENSE-zlib.txt"
cp /usr/share/doc/mingw-w64-x86-64-dev/copyright "$OUT/LICENSE-mingw-w64.txt"
{
    echo "ffmpeg $FFMPEG_VERSION, built by packaging/ffmpeg/build.sh in debian:trixie"
    echo "source: https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz (signature checked: $FFMPEG_KEY)"
    echo "compiler: $(x86_64-w64-mingw32-gcc --version | head -1)"
    echo "zlib: $(dpkg-query -W -f '${Version}' libz-mingw-w64-dev), mingw-w64: $(dpkg-query -W -f '${Version}' mingw-w64-x86-64-dev)"
    echo "configure:$(echo $FLAGS | tr '\n' ' ')"
    echo
    cd "$OUT" && sha256sum ffmpeg.exe "ffmpeg-$FFMPEG_VERSION.tar.xz"
} > "$OUT/BUILD.txt"
[ -n "${OWNER:-}" ] && chown -R "$OWNER" "$OUT"
cat "$OUT/BUILD.txt"
