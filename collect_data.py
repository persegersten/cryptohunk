def collect_portfolio():
    # Assuming config is available globally or imported
    currencies_to_include = set(config.Config.currencies)  # List from the configuration
    currencies_to_include.add('USDC')  # Adding USDC to the list

    # Logic for retrieving the portfolio...
    portfolio = get_portfolio_data()  # Hypothetical function to get raw portfolio data

    filtered_portfolio = [asset for asset in portfolio if asset['currency'] in currencies_to_include]  # Filter for specified currencies

    return filtered_portfolio