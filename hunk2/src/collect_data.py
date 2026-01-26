class CollectData:
    def __init__(self):
        self.currency_rate_history = []
        self.portfolio_data = []
        self.trade_history = []

    def add_currency_rate(self, currency_rate):
        self.currency_rate_history.append(currency_rate)

    def add_portfolio_data(self, data):
        self.portfolio_data.append(data)

    def add_trade(self, trade):
        self.trade_history.append(trade)

    def get_currency_rate_history(self):
        return self.currency_rate_history

    def get_portfolio_data(self):
        return self.portfolio_data

    def get_trade_history(self):
        return self.trade_history