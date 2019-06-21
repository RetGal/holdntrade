#!/bin/sh

holdntradeDir=/home/bit/trader

cd $holdntradeDir
find -name "*.pid" -type f 2>/dev/null | while read file; 
do
  read pid param < $file 
  kill -0 $pid 2>/dev/null
  if [ $? -eq 1 ]; then
    echo $param is dead
    tmux has-session -t $param 2>/dev/null
    if [ $? -eq 1 ]; then
      tmux new -t $param
    fi
    tmux send-keys -t "$param" C-z "$holdntradeDir/holdntrade.py $param -ac" C-m
  else
    echo $param is running
  fi
done

