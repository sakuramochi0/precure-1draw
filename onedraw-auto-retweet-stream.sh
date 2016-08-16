#!/bin/zsh
genre=$1; shift
pids=$(python3 -c "import psutil; pids = [p.pid for p in psutil.process_iter() if 'onedraw.py $genre auto_retweet_stream()' in ' '.join(p.cmdline())]; print(' '.join(map(str, pids)))")
if [ ! $pids ]; then
    onedraw $genre 'auto_retweet_stream()' >> $genre/auto_retweet_stream.log
fi
