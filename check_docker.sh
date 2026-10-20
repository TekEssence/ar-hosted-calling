#!/bin/bash
sudo docker info | grep -A5 "Docker Root Dir"
df -h /
df -h /mnt