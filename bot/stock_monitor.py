import yfinance as yf
import logging

logger = logging.getLogger(__name__)

class StockMonitor:
    def __init__(self, config_manager):
        self.config = config_manager
        
    def check_market(self):
        """
        Checks major indices for significant moves.
        """
        if not self.config.get("stock_alerts_enabled"):
            return None

        market = self.config.get("stock_market", "US")
        symbol = "^GSPC" if market == "US" else "^STOXX50E" # S&P 500 or Euro Stoxx 50
        
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="2d")
            
            if len(hist) < 2:
                return None
                
            close_prev = hist['Close'].iloc[-2]
            close_curr = hist['Close'].iloc[-1]
            
            change_pct = ((close_curr - close_prev) / close_prev) * 100
            
            threshold = 1.0 # 1% move
            if self.config.get("alert_aggressiveness") == "high":
                threshold = 0.5
            
            if change_pct > threshold:
                return f"📈 Stock Alert: {symbol} is UP {change_pct:.2f}% (Strong Buy Signal?)"
            elif change_pct < -threshold:
                return f"📉 Stock Alert: {symbol} is DOWN {change_pct:.2f}% (Market Dip)"
            
        except Exception as e:
            logger.error(f"Stock monitor error: {e}")
            
        return None
