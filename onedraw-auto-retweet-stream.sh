#!/bin/zsh
genre=$1; shift
pids=$(ps x | grep -i onedraw.py | grep -v ipython | grep -v grep | grep python | grep auto_retweet_stream | grep $genre | perl -pi -e 's/(\d+).+/$1/')
time=$(date +%H%M)

# if 2105 > time > 2100, kill the program
# if [ $pids ] && [ 2105 -gt $time ] && [ $time -gt 2100 ]; then
#     for pid in $pids; do
# 	kill $pid
#     done
# fi
# if not running, restart the program
if [ ! $pids ]; then
    onedraw $genre 'auto_retweet_stream()' >> $genre/auto_retweet_stream.log
fi
