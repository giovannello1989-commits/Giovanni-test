from peewee import *
import datetime

db = SqliteDatabase('trading_bot.db')

class BaseModel(Model):
    class Meta:
        database = db

class Position(BaseModel):
    symbol = CharField()
    quantity = FloatField()
    average_entry_price = FloatField()
    current_value = FloatField(default=0.0) # Estimated current value
    is_open = BooleanField(default=True)
    opened_at = DateTimeField(default=datetime.datetime.now)
    last_updated = DateTimeField(default=datetime.datetime.now)

class Trade(BaseModel):
    symbol = CharField()
    side = CharField() # BUY or SELL
    quantity = FloatField()
    price = FloatField()
    cost = FloatField() # quantity * price
    timestamp = DateTimeField(default=datetime.datetime.now)
    pnl = FloatField(null=True) # For sells

class AuditLog(BaseModel):
    timestamp = DateTimeField(default=datetime.datetime.now)
    action = CharField()
    details = TextField()
    capital_exposure = FloatField()

class ForexWatch(BaseModel):
    """
    Symbols like 'EURUSD=X' (yfinance).
    """
    symbol = CharField(unique=True)
    lookback_bars = IntegerField(default=5)
    rise_threshold_pct = FloatField(default=0.05)
    fall_threshold_pct = FloatField(default=0.05)
    interval = CharField(default="1m")
    is_active = BooleanField(default=True)
    last_rise_alert_at = DateTimeField(null=True)
    last_fall_alert_at = DateTimeField(null=True)

class ForexHolding(BaseModel):
    """
    Manual holding the user tells us about via Telegram.
    We only alert; we do not trade forex.
    """
    symbol = CharField()
    is_open = BooleanField(default=True)
    bought_at = DateTimeField(default=datetime.datetime.now)
    bought_price = FloatField(null=True)

def init_db():
    if db.is_closed():
        db.connect(reuse_if_open=True)
    db.create_tables([Position, Trade, AuditLog, ForexWatch, ForexHolding], safe=True)

def get_total_exposure():
    # Calculate total cost basis of all open positions
    # Exposure = Sum(quantity * average_entry_price) for all open positions
    # OR should it be current market value?
    # Prompt says: "NEVER exceed 100 USDC exposure". Usually means cost basis.
    # If I buy $100 worth, exposure is $100. If it goes to $200, exposure is $100 (initial capital at risk) or $200 (current value)?
    # "MAX TOTAL CAPITAL: 100 USDC". This usually refers to the initial investment amount allowed.
    # I will track Cost Basis.
    positions = Position.select().where(Position.is_open == True)
    total_cost = 0.0
    for pos in positions:
        total_cost += (pos.quantity * pos.average_entry_price)
    return total_cost
