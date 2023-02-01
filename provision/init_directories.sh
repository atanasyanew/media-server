#!/bin/bash
# The script creates folder structure required by he compose file.

# Declare the directories
dirs=(
  "content/media/movies favorite"
  "content/media/movies"
  "content/media/music"
  "content/media/tv"
  "content/torrents/movies"
  "content/torrents/music"
  "content/torrents/tv"
  "content/usenet/movies"
  "content/usenet/music"
  "content/usenet/tv"
  "provision"
)

# Loop over the directories
for dir in "${dirs[@]}"; do
  # Create the directory
  mkdir -p "$dir"

  # Create the .gitkeep file
  touch "$dir/.gitkeep"
done