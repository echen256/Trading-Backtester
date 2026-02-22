for file in *.csv; do
    ticker=$(basename "$file" .csv | cut -d'_' -f1)
    
    # Backup original
    cp "$file" "${file}.backup"
    
    # Add ticker column
    sed "1s/^/ticker,/" "$file" > temp.csv
    awk -v ticker="$ticker" 'BEGIN{FS=OFS=","} NR>1 {$0=ticker "," $0} 1' temp.csv > "$file"
    
    rm temp.csv
done