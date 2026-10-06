import React, { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useDrag } from '@use-gesture/react';
import { ChevronLeft, RotateCw } from 'lucide-react';
import axios from 'axios';

const API_BASE = '/api';

export default function MobileCurationView({
  results,
  setResults,
  globalTags,
  initialIndex,
  onClose,
  getAssetImgSrc
}) {
  const [index, setIndex] = useState(initialIndex);
  const [direction, setDirection] = useState(0);
  const [isProcessing, setIsProcessing] = useState(false);
  const [viewerTags, setViewerTags] = useState([]);

  const currentAsset = results[index];

  // Flatten global tags into a unique list for the quick-action pills
  const allAvailableTags = useMemo(() => {
    if (!globalTags) return [];
    const tags = Object.values(globalTags).flat();
    return [...new Set(tags)];
  }, [globalTags]);

  // Load tags for the current image
  useEffect(() => {
    if (currentAsset && currentAsset.originalPath) {
      setViewerTags([]); // clear while loading
      axios.get(`${API_BASE}/tags?path=${encodeURIComponent(currentAsset.originalPath)}`)
        .then(res => setViewerTags(res.data.tags || []))
        .catch(err => console.error("Failed to load tags", err));
    }
  }, [currentAsset]);

  // Eager preloading for the next 3 images to ensure smooth swiping
  useEffect(() => {
    const preloadImages = () => {
      for (let i = 1; i <= 3; i++) {
        if (index + i < results.length) {
          const img = new Image();
          img.src = getAssetImgSrc(results[index + i], true);
        }
      }
    };
    preloadImages();
  }, [index, results, getAssetImgSrc]);

  const paginate = (newDirection) => {
    const nextIndex = index + newDirection;
    if (nextIndex >= 0 && nextIndex < results.length) {
      setDirection(newDirection);
      setIndex(nextIndex);
    }
  };

  const bind = useDrag(({ active, movement: [mx], direction: [xDir], cancel, velocity: [vx] }) => {
    // If the user drags far enough or fast enough, paginate
    if (!active && (Math.abs(mx) > window.innerWidth / 3 || vx > 0.5)) {
      if (xDir > 0) {
        paginate(-1); // Swipe right -> Previous image
      } else {
        paginate(1);  // Swipe left -> Next image
      }
      cancel();
    }
  }, { axis: 'x' });

  const handleRotate = async () => {
    if (!currentAsset || isProcessing) return;
    setIsProcessing(true);
    try {
      await axios.post(`${API_BASE}/rotate`, { paths: [currentAsset.originalPath] });
      setResults(results.map((r, i) => i === index ? {...r, rotated: Date.now()} : r));
    } catch (err) {
      alert(`Rotate failed: ${err.message}`);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleToggleTag = async (tag) => {
    if (!currentAsset || isProcessing) return;
    const isTagApplied = viewerTags.includes(tag);
    setIsProcessing(true);
    
    // Optimistic UI update for immediate feedback
    if (isTagApplied) {
      setViewerTags(viewerTags.filter(t => t !== tag));
    } else {
      setViewerTags([...viewerTags, tag]);
    }

    try {
      await axios.post(`${API_BASE}/tags`, {
        paths: [currentAsset.originalPath],
        tag: tag,
        action: isTagApplied ? 'remove' : 'add'
      });
      // Optionally provide haptic feedback here
      if (navigator.vibrate) navigator.vibrate(50);
    } catch (err) {
      alert(`Tagging failed: ${err.message}`);
      // Revert optimistic update on error
      if (isTagApplied) {
        setViewerTags([...viewerTags, tag]);
      } else {
        setViewerTags(viewerTags.filter(t => t !== tag));
      }
    } finally {
      setIsProcessing(false);
    }
  };

  const variants = {
    enter: (direction) => ({
      x: direction > 0 ? 1000 : -1000,
      opacity: 0
    }),
    center: {
      zIndex: 1,
      x: 0,
      opacity: 1
    },
    exit: (direction) => ({
      zIndex: 0,
      x: direction < 0 ? 1000 : -1000,
      opacity: 0
    })
  };

  if (!currentAsset) return null;

  return (
    <div style={{ position: 'fixed', inset: 0, backgroundColor: 'black', zIndex: 100, display: 'flex', flexDirection: 'column' }}>
      
      {/* Top Bar */}
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, padding: '16px', zIndex: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <button 
          onClick={onClose}
          style={{ background: 'rgba(30, 41, 59, 0.8)', border: 'none', borderRadius: '50%', width: '48px', height: '48px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white' }}
        >
          <ChevronLeft size={28} />
        </button>
        <div style={{ color: 'white', backgroundColor: 'rgba(0,0,0,0.5)', padding: '4px 12px', borderRadius: '12px', fontWeight: 'bold' }}>
          {index + 1} / {results.length}
        </div>
      </div>

      {/* Swipeable Image Area */}
      <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }} {...bind()}>
        <AnimatePresence initial={false} custom={direction}>
          <motion.img
            key={index}
            src={getAssetImgSrc(currentAsset, true)}
            custom={direction}
            variants={variants}
            initial="enter"
            animate="center"
            exit="exit"
            transition={{
              x: { type: "spring", stiffness: 300, damping: 30 },
              opacity: { duration: 0.2 }
            }}
            style={{
              position: 'absolute',
              width: '100%',
              height: '100%',
              objectFit: 'contain',
              userSelect: 'none',
              touchAction: 'none' // Prevents browser pull-to-refresh while swiping
            }}
            draggable={false}
          />
        </AnimatePresence>
      </div>

      {/* Bottom Action Bar (Material Design 3 Solid) */}
      <div style={{ 
        backgroundColor: '#1e293b', 
        padding: '24px 16px 36px 16px', 
        borderTopLeftRadius: '24px', 
        borderTopRightRadius: '24px',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
        zIndex: 10,
        boxShadow: '0 -4px 20px rgba(0,0,0,0.3)'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
           
           <button 
             onClick={handleRotate}
             disabled={isProcessing}
             style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', background: 'none', border: 'none', color: '#cbd5e1', opacity: isProcessing ? 0.5 : 1 }}
           >
             <div style={{ width: '56px', height: '56px', borderRadius: '50%', backgroundColor: 'rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '8px' }}>
               <RotateCw size={24} />
             </div>
             <span style={{ fontSize: '13px', fontWeight: '500' }}>Rotate</span>
           </button>
           
           {/* Tags Container (Horizontal scroll) */}
           <div style={{ display: 'flex', gap: '8px', overflowX: 'auto', padding: '0 8px', flex: 1 }}>
             {allAvailableTags.length === 0 && (
               <span style={{ color: '#94a3b8', padding: '14px', fontStyle: 'italic', margin: '0 auto' }}>No global tags configured.</span>
             )}
             
             {allAvailableTags.map(tag => {
               const isActive = viewerTags.includes(tag);
               return (
                 <button 
                   key={tag}
                   onClick={() => handleToggleTag(tag)}
                   disabled={isProcessing}
                   style={{ 
                     padding: '14px 24px', 
                     borderRadius: '32px', 
                     backgroundColor: isActive ? '#3b82f6' : 'rgba(255,255,255,0.1)', 
                     color: 'white', 
                     border: isActive ? '1px solid #60a5fa' : '1px solid transparent', 
                     fontWeight: 'bold', 
                     fontSize: '16px',
                     whiteSpace: 'nowrap',
                     opacity: isProcessing ? 0.7 : 1,
                     transition: 'all 0.2s'
                   }}
                 >
                    {tag}
                 </button>
               );
             })}
           </div>

           {/* Transparent spacer to balance the flexbox since we removed the Trash button */}
           <div style={{ width: '56px' }}></div>
        </div>
      </div>

    </div>
  );
}
