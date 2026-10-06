i want to make a api which can run with any trading app like Dhan, Stokxkart etc to ititiate trade buy, sl, tp, sell on a particular stocks scripts on selected quantity based on following conditions: 
1. first to check vwap value of stock whether current price in greter than or less than the vwap. if current price is greater than VAWAP than we will plan to buy that stock
 when follwing both condition will satisfy on selected timeframe ( 1 min, 3 min, 5 min)
  a. when RSI(21) is cross  above or greather than  Exp moving average of RsI(21) of period of 21. 
 and
 b price is greather than or corss above of supertrend ( 21, 0.618)
2. After taking buy trade  when we will exit  when follwing condition will satisfy 
a. when rsi(21) is crossed below on closing on selected timeframe of ema(RSI(21), 9)
or 
b price is less than supertrend ( 21, 0.618)
 othwewise when loss is cross 3% sl should be hit
api should ask again before initiate trade in the selected stock on approval it will repeat above steps again.


