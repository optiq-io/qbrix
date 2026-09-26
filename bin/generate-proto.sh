#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/.."
PROTO_DIR="$ROOT_DIR/proto"
OUT_DIR="$ROOT_DIR/lib/proto/qbrixproto"

# pin grpcio-tools to generate protobuf 5.x compatible stubs.
# grpcio-tools >=1.71.0 generates protobuf 7.x stubs, but the gRPC python
# ecosystem (grpcio-health-checking) still requires protobuf <7.0.0.
# we use a temporary venv so the pinned grpcio-tools doesn't conflict
# with the project's runtime protobuf version.
PROTO_GRPCIO_TOOLS_VERSION="1.76.0"
PROTO_VENV="$ROOT_DIR/.proto-venv"

echo "Setting up proto generation environment (grpcio-tools==$PROTO_GRPCIO_TOOLS_VERSION)..."
uv venv "$PROTO_VENV" --python 3.10 -q
uv pip install --python "$PROTO_VENV/bin/python" -q \
    "grpcio-tools==$PROTO_GRPCIO_TOOLS_VERSION" \
    "mypy-protobuf"

PROTO_FILES=$(find "$PROTO_DIR" -name "*.proto" | sort)

echo "Generating proto stubs..."
PATH="$PROTO_VENV/bin:$PATH" "$PROTO_VENV/bin/python" -m grpc_tools.protoc \
    --proto_path="$PROTO_DIR" \
    --python_out="$OUT_DIR" \
    --grpc_python_out="$OUT_DIR" \
    --mypy_out="$OUT_DIR" \
    $PROTO_FILES

echo "Fixing imports for package use..."

# detect os for sed -i compatibility
if [[ "$(uname)" == "Darwin" ]]; then
    SED_INPLACE=(sed -i '')
else
    SED_INPLACE=(sed -i)
fi

# fix imports in _pb2.py files (protobuf)
for file in "$OUT_DIR"/*_pb2.py; do
    if [[ -f "$file" ]]; then
        "${SED_INPLACE[@]}" 's/^import \([a-z_]*_pb2\) as /from qbrixproto import \1 as /' "$file"
    fi
done

# fix imports in _pb2_grpc.py files (grpc)
for file in "$OUT_DIR"/*_pb2_grpc.py; do
    if [[ -f "$file" ]]; then
        "${SED_INPLACE[@]}" 's/^import \([a-z_]*_pb2\) as /from qbrixproto import \1 as /' "$file"
    fi
done

# clean up
rm -rf "$PROTO_VENV"

echo "Done! Proto stubs generated in $OUT_DIR"
