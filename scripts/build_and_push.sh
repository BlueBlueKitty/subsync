#!/usr/bin/env sh
set -eu

IMAGE_NAME="${IMAGE_NAME:-bluebluekitty/subsync}"
VERSION="${VERSION:-v0.1.1}"
VERSION_NO_V="${VERSION#v}"
PLATFORM="${PLATFORM:-linux/amd64}"

echo "Building ${IMAGE_NAME}:${VERSION} and ${IMAGE_NAME}:latest"
docker build \
  --platform "${PLATFORM}" \
  --build-arg APP_VERSION="${VERSION_NO_V}" \
  -t "${IMAGE_NAME}:${VERSION}" \
  -t "${IMAGE_NAME}:latest" \
  .

echo "Pushing ${IMAGE_NAME}:${VERSION}"
docker push "${IMAGE_NAME}:${VERSION}"

echo "Pushing ${IMAGE_NAME}:latest"
docker push "${IMAGE_NAME}:latest"

echo "Done"
