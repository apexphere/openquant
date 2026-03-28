#!/bin/bash
# Build the dashboard and copy output to openquant/static/
set -e
cd "$(dirname "$0")/../dashboard"

echo "Installing dependencies..."
npm install

echo "Building dashboard..."
npm run build

echo "Copying build output to openquant/static/..."
rm -rf ../openquant/static/*
cp -r dist/* ../openquant/static/

echo "Dashboard build complete."
