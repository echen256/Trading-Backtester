import { useState, useEffect } from 'react';
import './Watchlist.css';

interface WatchlistProps {
  onTickerSelect: (ticker: string) => void;
  currentTicker: string;
}

export function Watchlist({ onTickerSelect, currentTicker }: WatchlistProps) {
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [newTicker, setNewTicker] = useState('');
  const [isAddingTicker, setIsAddingTicker] = useState(false);
  const [isLoaded, setIsLoaded] = useState(false);

  // Load watchlist from localStorage on component mount
  useEffect(() => {
    const savedWatchlist = localStorage.getItem('trading-watchlist');
    if (savedWatchlist) {
      try {
        const parsedWatchlist = JSON.parse(savedWatchlist);
        if (Array.isArray(parsedWatchlist)) {
          setWatchlist(parsedWatchlist);
        }
      } catch (error) {
        console.error('Error loading watchlist from localStorage:', error);
      }
    }
    setIsLoaded(true);
  }, []);

  // Save watchlist to localStorage whenever it changes (but only after initial load)
  useEffect(() => {
    if (isLoaded) {
      localStorage.setItem('trading-watchlist', JSON.stringify(watchlist));
    }
  }, [watchlist, isLoaded]);

  const handleAddTicker = (e: React.FormEvent) => {
    e.preventDefault();
    const ticker = newTicker.trim().toUpperCase();
    if (ticker && !watchlist.includes(ticker)) {
      setWatchlist(prev => [...prev, ticker]);
      setNewTicker('');
      setIsAddingTicker(false);
    }
  };

  const handleRemoveTicker = (tickerToRemove: string) => {
    setWatchlist(prev => prev.filter(ticker => ticker !== tickerToRemove));
  };

  const handleTickerClick = (ticker: string) => {
    onTickerSelect(ticker);
  };

  const handleClearWatchlist = () => {
    if (window.confirm('Are you sure you want to clear the entire watchlist?')) {
      setWatchlist([]);
    }
  };

  return (
    <div className="watchlist">
      <div className="watchlist-header">
        <h3>Watchlist</h3>
        <button 
          className="add-ticker-btn"
          onClick={() => setIsAddingTicker(true)}
          disabled={isAddingTicker}
        >
          +
        </button>
      </div>
      
      {isAddingTicker && (
        <form onSubmit={handleAddTicker} className="add-ticker-form">
          <input
            type="text"
            value={newTicker}
            onChange={(e) => setNewTicker(e.target.value)}
            placeholder="Enter ticker"
            className="ticker-input"
            autoFocus
          />
          <div className="form-buttons">
            <button type="submit" className="submit-btn">Add</button>
            <button 
              type="button" 
              className="cancel-btn"
              onClick={() => {
                setIsAddingTicker(false);
                setNewTicker('');
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      <div className="watchlist-items">
        {watchlist.map(ticker => (
          <div 
            key={ticker} 
            className={`watchlist-item ${ticker === currentTicker ? 'active' : ''}`}
            onClick={() => handleTickerClick(ticker)}
          >
            <span className="ticker-symbol">{ticker}</span>
            <button 
              className="remove-btn"
              onClick={(e) => {
                e.stopPropagation();
                handleRemoveTicker(ticker);
              }}
            >
              ×
            </button>
          </div>
        ))}
      </div>
      
      {watchlist.length > 0 && (
        <div className="watchlist-footer">
          <button 
            className="clear-watchlist-btn"
            onClick={handleClearWatchlist}
          >
            Clear Watchlist
          </button>
        </div>
      )}
    </div>
  );
}