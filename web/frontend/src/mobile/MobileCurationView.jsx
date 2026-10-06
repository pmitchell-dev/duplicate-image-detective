import React, { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useDrag } from '@use-gesture/react';
import { ChevronLeft, ChevronRight, RotateCw, Tag as TagIcon, X } from 'lucide-react';
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
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  const currentAsset = results[index];

  // Flatten global tags into a unique list for the drawer
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

  // Eager preloading for just the next 1 image to save RAM and DSL bandwidth
  useEffect(() => {
    const preloadImages = () => {
      if (index + 1 < results.length) {
        const img = new Image();
        img.src = getAssetImgSrc(results[index + 1], true);
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
    // Prevent swiping the image if the tag drawer is open
    if (isDrawerOpen) return;
    
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
    enter: (direction) => ({ x: direction > 0 ? 1000 : -1000, opacity: 0 }),
    center: { zIndex: 1, x: 0, opacity: 1 },
    exit: (direction) => ({ zIndex: 0, x: direction < 0 ? 1000 : -1000, opacity: 0 })
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
      <div style={{ flex: 1, position: 'relative', overflow: 'hidden', touchAction: 'pan-y' }} {...bind()}>
        {/* Floating Navigation Arrows */}
        {index > 0 && (
          <button 
            onClick={(e) => { e.stopPropagation(); paginate(-1); }}
            style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', zIndex: 10, background: 'rgba(15, 23, 42, 0.5)', backdropFilter: 'blur(4px)', border: 'none', borderRadius: '50%', width: '44px', height: '44px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white' }}
          >
            <ChevronLeft size={28} />
          </button>
        )}
        {index < results.length - 1 && (
          <button 
            onClick={(e) => { e.stopPropagation(); paginate(1); }}
            style={{ position: 'absolute', right: '10px', top: '50%', transform: 'translateY(-50%)', zIndex: 10, background: 'rgba(15, 23, 42, 0.5)', backdropFilter: 'blur(4px)', border: 'none', borderRadius: '50%', width: '44px', height: '44px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white' }}
          >
            <ChevronRight size={28} />
          </button>
        )}

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

        {/* Floating Applied Tags Overlay */}
        <div style={{ 
          position: 'absolute', 
          bottom: '24px', 
          left: '16px', 
          right: '16px',
          display: 'flex',
          flexWrap: 'wrap',
          gap: '8px',
          zIndex: 5,
          pointerEvents: 'none' // Let swipes pass through to the image
        }}>
          {viewerTags.map(tag => (
            <motion.div 
              key={tag}
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              style={{ 
                padding: '6px 14px', 
                backgroundColor: 'rgba(0,0,0,0.65)', 
                backdropFilter: 'blur(4px)',
                color: 'white', 
                borderRadius: '16px', 
                fontSize: '13px', 
                fontWeight: '600',
                border: '1px solid rgba(255,255,255,0.2)',
                boxShadow: '0 2px 8px rgba(0,0,0,0.3)'
              }}
            >
              {tag}
            </motion.div>
          ))}
        </div>
      </div>

      {/* Minimalist Bottom Action Bar */}
      <div style={{ 
        backgroundColor: '#1e293b', 
        padding: '20px 16px 36px 16px', 
        borderTopLeftRadius: '24px', 
        borderTopRightRadius: '24px',
        display: 'flex',
        justifyContent: 'center',
        gap: '48px',
        zIndex: 10,
        boxShadow: '0 -4px 20px rgba(0,0,0,0.3)'
      }}>
         <button 
           onClick={handleRotate}
           disabled={isProcessing}
           style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', background: 'none', border: 'none', color: '#cbd5e1', opacity: isProcessing ? 0.5 : 1 }}
         >
           <div style={{ width: '64px', height: '64px', borderRadius: '50%', backgroundColor: 'rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '8px' }}>
             <RotateCw size={28} />
           </div>
           <span style={{ fontSize: '14px', fontWeight: '500' }}>Rotate</span>
         </button>

         <button 
           onClick={() => setIsDrawerOpen(true)}
           style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', background: 'none', border: 'none', color: '#60a5fa' }}
         >
           <div style={{ width: '64px', height: '64px', borderRadius: '50%', backgroundColor: 'rgba(59, 130, 246, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '8px' }}>
             <TagIcon size={28} />
           </div>
           <span style={{ fontSize: '14px', fontWeight: '500' }}>Tags</span>
         </button>
      </div>

      {/* Tag Drawer (Bottom Sheet Modal) */}
      <AnimatePresence>
        {isDrawerOpen && (
          <>
            {/* Backdrop */}
            <motion.div 
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setIsDrawerOpen(false)}
              style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.6)', zIndex: 101, touchAction: 'none' }}
            />
            {/* Drawer */}
            <motion.div 
              initial={{ y: '100%' }}
              animate={{ y: 0 }}
              exit={{ y: '100%' }}
              transition={{ type: 'spring', damping: 25, stiffness: 300 }}
              style={{ 
                position: 'fixed', 
                bottom: 0, 
                left: 0, 
                right: 0, 
                backgroundColor: '#1e293b', 
                borderTopLeftRadius: '24px', 
                borderTopRightRadius: '24px',
                padding: '24px 16px 48px 16px',
                zIndex: 102,
                maxHeight: '80vh',
                display: 'flex',
                flexDirection: 'column',
                boxShadow: '0 -10px 40px rgba(0,0,0,0.5)'
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <h3 style={{ margin: 0, color: 'white', fontSize: '20px' }}>Manage Tags</h3>
                <button 
                  onClick={() => setIsDrawerOpen(false)}
                  style={{ background: 'rgba(255,255,255,0.1)', border: 'none', borderRadius: '50%', width: '36px', height: '36px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#cbd5e1' }}
                >
                  <X size={20} />
                </button>
              </div>

              <div style={{ overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '24px' }}>
                {Object.keys(globalTags || {}).length === 0 && (
                  <span style={{ color: '#94a3b8', fontStyle: 'italic' }}>No global tags configured.</span>
                )}
                
                {Object.entries(globalTags || {}).map(([category, tags]) => (
                  <div key={category} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <h4 style={{ margin: 0, color: '#94a3b8', fontSize: '13px', textTransform: 'uppercase', letterSpacing: '1px', fontWeight: 'bold' }}>{category}</h4>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                      {tags.map(tag => {
                        const isActive = viewerTags.includes(tag);
                        return (
                          <button 
                            key={tag}
                            onClick={() => handleToggleTag(tag)}
                            disabled={isProcessing}
                            style={{ 
                              padding: '8px 16px', 
                              borderRadius: '32px', 
                              backgroundColor: isActive ? '#3b82f6' : 'transparent', 
                              color: isActive ? 'white' : '#cbd5e1', 
                              border: isActive ? '1px solid #3b82f6' : '1px solid rgba(255,255,255,0.2)', 
                              fontWeight: '600', 
                              fontSize: '14px',
                              opacity: isProcessing ? 0.7 : 1,
                              transition: 'all 0.2s'
                            }}
                          >
                             {tag}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

    </div>
  );
}
