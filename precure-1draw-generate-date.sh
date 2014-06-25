#!/bin/zsh
cd /Users/shuuji/doc/pro/python/precure-1draw/
./precure_1draw.py 'update_themes()'
./precure_1draw.py 'generate_date_html()' >> generate_date_html.log
./chart.py
./precure_1draw.py 'generate_index_html()'
