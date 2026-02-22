# Technical Debt & Future Improvements

## Real-time Data Integration
**Status**: Temporarily disabled for backtesting focus  
**Issue**: Real-time WebSocket data was causing conflicts with historical data updates  
**Future Work**: 
- Re-integrate WebSocket for live trading dashboard mode
- Implement mode switching (backtesting vs. live trading)
- Handle data source prioritization (historical vs. real-time)
- Add data synchronization strategy for mixed sources

## Memory Management - Bar Data Clearing
**Status**: Not implemented  
**Issue**: Continuous historical data loading can accumulate unlimited bars in memory  
**Future Work**:
- Implement sliding window approach (e.g., keep only 50,000 most recent bars)
- Add user preference for data retention limit
- Implement data virtualization for very large datasets
- Add memory usage monitoring and warnings
- Consider data persistence to local storage for offline access

## Performance Optimizations
**Status**: Basic implementation  
**Areas for improvement**:
- Batch `update()` calls for multiple bars to reduce render cycles
- Implement data compression for stored historical data
- Add data caching strategy for frequently accessed ranges
- Consider Web Workers for heavy data processing
- Optimize chart rendering for datasets >100k bars

## User Experience Enhancements
**Status**: Basic functionality  
**Future improvements**:
- Add progress indicators for large data loads
- Implement smart preloading based on user scroll patterns
- Add data export functionality (CSV, JSON)
- Implement bookmarking of specific time ranges
- Add chart annotations and drawing tools

## Error Handling & Resilience
**Status**: Basic error notifications  
**Improvements needed**:
- Implement retry logic for failed API calls
- Add offline mode with cached data
- Better error messaging with suggested actions
- Implement graceful degradation for chart rendering failures
- Add data validation before chart updates

## Data Quality & Validation
**Status**: Minimal validation  
**Future work**:
- Implement data gap detection and handling
- Add data anomaly detection (price spikes, missing timestamps)
- Implement data normalization for different timeframes
- Add data source quality indicators
- Implement data correction mechanisms for bad ticks

## API & Backend Integration
**Status**: Basic REST API integration  
**Enhancements needed**:
- Implement API rate limiting and throttling
- Add support for multiple data providers
- Implement data source failover mechanisms
- Add API key rotation and management
- Implement data subscription management for premium features