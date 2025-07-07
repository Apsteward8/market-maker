# ProphetX Market Maker

An automated market making system for ProphetX betting exchange that copies odds from Pinnacle Sports via The Odds API.

## Strategy Overview

This system implements a **market making strategy** that:

1. **Sources Sharp Odds** - Uses The Odds API to get real-time odds from Pinnacle Sports
2. **Creates Liquidity** - Places opposing bets on ProphetX to offer the same odds to other users
3. **Manages Risk** - Tracks positions and exposure across all markets
4. **Updates Continuously** - Adjusts prices when Pinnacle odds change

### Example Market Making Flow

```
Pinnacle: Djokovic -110, Nadal +100
↓
Our ProphetX Bets:
- Bet Djokovic at +110 (offers -110 to market)
- Bet Nadal at -100 (offers +100 to market)
↓
Result: We've copied Pinnacle's exact odds for other users
```

## Features

### 🎾 Tennis Focus
- Covers professional baseball tournaments (ATP, WTA, Grand Slams)
- Supports moneyline, spreads, and totals markets
- Pre-game markets only (no live betting)

### 📊 Real-Time Odds Synchronization  
- Polls Pinnacle odds every 60 seconds (configurable)
- Automatically updates ProphetX bets when odds change
- Efficient API usage with smart request management

### ⚖️ Risk Management
- Position limits per event and total portfolio
- Automatic market pause when approaching risk limits
- Comprehensive exposure tracking and reporting

### 🛡️ Safety Features
- **Dry run mode** - Test strategy without placing real bets
- **Configurable limits** - Set maximum exposures and bet sizes
- **Error handling** - Robust error recovery and logging

## Quick Start

### 1. Installation

```bash
# Clone/download the project
cd prophetx-market-maker

# Install dependencies
pip install -r requirements.txt
```

### 2. Get API Keys

**The Odds API:**
1. Sign up at [The Odds API](https://the-odds-api.com/)
2. Purchase a high-usage plan (15M credits recommended)
3. Get your API key

**ProphetX:**
1. Get your ProphetX access key and secret key
2. Start with sandbox environment for testing

### 3. Configuration

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your API keys
ODDS_API_KEY=your_odds_api_key_here
PROPHETX_ACCESS_KEY=your_access_key_here
PROPHETX_SECRET_KEY=your_secret_key_here

# Keep dry run mode enabled for testing
DRY_RUN_MODE=true
```

### 4. Run the System

```bash
# Start the API server
python run.py

# Or use uvicorn directly
uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

### 5. Access the Interface

- **API Documentation**: http://127.0.0.1:8001/docs
- **Health Check**: http://127.0.0.1:8001/health

## API Endpoints

### Market Making Control
- `POST /markets/start` - Start automated market making
- `POST /markets/stop` - Stop market making system
- `GET /markets/status` - Get system status and statistics

### Portfolio Management
- `GET /markets/portfolio` - Get portfolio summary
- `GET /markets/events` - List all managed events
- `GET /markets/events/{id}` - Get specific event details

### Odds and Data
- `GET /markets/odds/latest` - Get latest Pinnacle odds
- `POST /markets/odds/refresh` - Refresh odds cache
- `GET /markets/api-usage` - Check Odds API usage

### Configuration
- `POST /markets/config/update` - Update runtime settings
- `GET /config/settings` - View current configuration

## Configuration Options

### Core Strategy Settings
```bash
# Market focus
FOCUS_SPORT=baseball
TARGET_BOOKMAKER=pinnacle
TARGET_MARKETS=h2h,spreads,totals

# Liquidity provision
DEFAULT_LIQUIDITY_AMOUNT=100.0  # $ per market side
MAX_EXPOSURE_PER_EVENT=500.0    # $ max exposure per event
MAX_EXPOSURE_TOTAL=2000.0       # $ total portfolio limit
```

### Risk Management
```bash
# Event filtering
MAX_EVENTS_TRACKED=30                    # Max concurrent events
EVENTS_LOOKAHEAD_HOURS=24               # Only events starting within 24h
MIN_TIME_BEFORE_START_MINUTES=15        # Stop markets 15min before start

# Position sizing
MIN_BET_SIZE=5.0
MAX_BET_SIZE=200.0
```

### System Performance
```bash
# Odds polling
ODDS_POLL_INTERVAL_SECONDS=60           # Check for odds changes every 60s
SIGNIFICANT_ODDS_CHANGE_THRESHOLD=0.02  # 2% change triggers update

# API limits
MAX_CONCURRENT_REQUESTS=10
REQUEST_TIMEOUT_SECONDS=30
```

## Understanding the Strategy

### Why Copy Pinnacle?
- **Sharpest Book**: Pinnacle is widely considered the most efficient sportsbook
- **Professional Action**: They welcome professional bettors, creating efficient lines
- **No Restrictions**: Unlike other books, Pinnacle doesn't limit winning players

### Market Making Logic
```
When Pinnacle offers: Djokovic -110, Nadal +100

We place on ProphetX:
- Bet: Djokovic +110 for $100 → Offers -110 to other users
- Bet: Nadal -100 for $100 → Offers +100 to other users

Result: ProphetX users see the same odds as Pinnacle
```

### Profit Sources
1. **Spread Capture** - When our bets get matched, we profit from bid-ask spreads
2. **Information Edge** - We have faster access to sharp pricing than most ProphetX users
3. **Market Making Premium** - Users pay slightly more for immediate liquidity

### Risk Management
- **Position Limits** - Never risk more than configured maximums
- **Time Limits** - Stop making markets close to event start
- **Odds Monitoring** - Continuous updates prevent stale pricing

## Safety and Risk Considerations

### Start Small and Safe
1. **Use Dry Run Mode** - Test extensively before going live
2. **Small Liquidity** - Start with $25-50 per market side
3. **Limited Events** - Begin with 5-10 events max
4. **Monitor Closely** - Watch for unexpected behavior

### Risk Factors
- **Execution Risk** - ProphetX outages or API issues
- **Odds Delay** - Our prices may lag behind market movements
- **Correlation Risk** - Multiple markets can move against us simultaneously
- **Platform Risk** - ProphetX-specific risks and limitations

### Best Practices
- Monitor total exposure constantly
- Set conservative position limits initially
- Test with sandbox environment extensively
- Have manual override procedures
- Keep detailed logs and performance records

## API Credit Management

With 15M monthly credits on The Odds API:

### Usage Calculation
- **30 events** × **24 hours** × **60 requests/hour** × **3 markets** = **129,600 credits/day**
- **Monthly usage**: ~3.9M credits (26% of limit)

### Optimization Tips
- Focus on higher-value tournaments
- Increase polling interval during off-peak hours
- Use event filtering to reduce unnecessary requests
- Monitor usage via `/markets/api-usage` endpoint

## Monitoring and Performance

### Key Metrics to Watch
- **Total Exposure** - Current risk across all positions
- **Success Rate** - Percentage of successful market updates
- **API Usage** - Credits consumed vs. available
- **Match Rate** - How often our bets get matched

### Dashboard Access
The FastAPI docs interface provides a complete dashboard for:
- Starting/stopping the system
- Monitoring current positions
- Viewing performance statistics
- Managing configuration

## Development and Testing

### Running Tests
```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run tests
pytest
```

### Local Development
```bash
# Run with auto-reload for development
uvicorn main:app --reload --log-level debug

# Access detailed logs
tail -f logs/market_maker.log
```

### Testing Strategy
1. **Unit Tests** - Test individual components
2. **Integration Tests** - Test API integrations  
3. **Dry Run Testing** - Full system test without real bets
4. **Paper Trading** - Track theoretical performance

## Production Deployment

### Environment Setup
- Use production ProphetX credentials
- Set `DRY_RUN_MODE=false` only when ready
- Configure appropriate logging and monitoring
- Set up database backups

### Monitoring
- Monitor API error rates and response times
- Track position P&L and exposure
- Set up alerts for risk limit breaches
- Log all bet placements and outcomes

## Troubleshooting

### Common Issues
- **API Rate Limits** - Increase polling intervals or reduce events
- **Stale Odds** - Check The Odds API connectivity
- **ProphetX Errors** - Verify credentials and sandbox settings
- **High Exposure** - Reduce position sizes or event count

### Getting Help
1. Check the logs in `/logs/` directory
2. Use `/markets/status` endpoint for system diagnostics
3. Review API usage with `/markets/api-usage`
4. Test individual components with dry run mode

## Disclaimer

This software is for educational and research purposes. Sports betting involves significant risk, and automated trading systems can amplify both gains and losses. Only bet what you can afford to lose, and ensure compliance with all applicable laws and regulations.

**Key Warnings:**
- Past performance does not guarantee future results
- Market making involves inventory risk
- Technical failures can result in unexpected exposure
- Regulatory compliance is your responsibility

## License

This project is provided as-is for educational purposes. Use at your own risk.