#!/bin/bash
# Kill stuck knowledge base processing processes

echo "Killing stuck processes..."
pkill -f "docker compose exec.*DocumentAdder"
pkill -f "docker compose exec.*add_documents"
pkill -f "python.*DocumentAdder"

echo "Checking if processes are killed..."
ps aux | grep -E "docker compose exec|DocumentAdder" | grep -v grep

echo "Done!"
