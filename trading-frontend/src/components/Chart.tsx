
import { AreaSeries, createChart, ColorType, CandlestickSeries } from 'lightweight-charts';
import React, { useEffect, useRef, useState } from 'react';

export const ChartComponent = props => {
 
    const [loadingMoreTime, setLoadingMoreTimer] = useState(0);

    const {
        data,
        colors: {
            backgroundColor = 'white',
            lineColor = '#2962FF',
            textColor = 'black',
            areaTopColor = '#2962FF',
            areaBottomColor = 'rgba(41, 98, 255, 0.28)',
        } = {},
        requestMore,
    } = props;

    const chartContainerRef = useRef();

    const loadMoreCallback = () => {
        if (loadingMoreTime > 0) return;
        setLoadingMoreTimer(1000);   
    }

    useEffect(() => {
        if (loadingMoreTime > 0) {
            setTimeout(() => {
                requestMore().then(() => {
                    setLoadingMoreTimer(0);
                })
            }, 1000);
        }
        console.log(loadingMoreTime)
      
    }, [loadingMoreTime])

    useEffect(
        () => {
            const handleResize = () => {
                chart.applyOptions({ width: chartContainerRef.current.clientWidth });
            };

            const chart = createChart(chartContainerRef.current, {
                layout: {
                    background: { type: ColorType.Solid, color: backgroundColor },
                    textColor,
                },
                width: 1400,
                height: 800
            });
            chart.timeScale().fitContent();
            chart.timeScale().subscribeVisibleLogicalRangeChange((range, loadingMore) => {
                const visibleRange = chart.timeScale().getVisibleRange();
                if (visibleRange && visibleRange.from) {
                    const firstPoint = data[0];
                    
                    // If we're close to the earliest data point, load more data
                    // You can adjust the threshold based on your needs
                    if (firstPoint && visibleRange.from <= firstPoint.time + 86400 ) { // Within 1 day of earliest data
                        setTimeout(() => {
                            loadMoreCallback();
                        }, 1000);
                
                    }
                
                }
            })

            const newSeries = chart.addSeries(CandlestickSeries, {  });
            newSeries.setData(data);

            window.addEventListener('resize', handleResize);

            return () => {
                window.removeEventListener('resize', handleResize);

                chart.remove();
            };
        },
        [data, backgroundColor, lineColor, textColor, areaTopColor, areaBottomColor]
    );

    return (
        <div
            ref={chartContainerRef}
        />
    );
};
