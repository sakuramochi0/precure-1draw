#!/bin/zsh
for f in *.yml; do
  cp $f bak/$f_`date +%Y-%m-%d_%H-%M`
done
