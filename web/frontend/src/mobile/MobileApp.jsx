import React, { useState } from 'react';
import MobileGrid from './MobileGrid';
import MobileCurationView from './MobileCurationView';

export default function MobileApp({ 
  serverUrl, 
  apiKey, 
  globalTags, 
  folders,
  selectedFolder,
  setSelectedFolder,
  loadFolderImages,
  results,
  setResults,
  error,
  loading,
  getAssetImgSrc,
  query,
  setQuery,
  handleSmartSearch,
  handleUntaggedSearch,
  logo
}) {
  const [viewingIndex, setViewingIndex] = useState(-1);

  // If viewingIndex is set, render the full screen Curation View
  if (viewingIndex >= 0) {
    return (
      <MobileCurationView 
        results={results}
        setResults={setResults}
        globalTags={globalTags}
        initialIndex={viewingIndex}
        onClose={() => setViewingIndex(-1)}
        getAssetImgSrc={getAssetImgSrc}
      />
    );
  }

  // Otherwise render the grid
  return (
    <MobileGrid 
      results={results}
      folders={folders}
      selectedFolder={selectedFolder}
      setSelectedFolder={setSelectedFolder}
      loadFolderImages={loadFolderImages}
      onImageClick={(index) => setViewingIndex(index)}
      getAssetImgSrc={getAssetImgSrc}
      loading={loading}
      error={error}
      query={query}
      setQuery={setQuery}
      handleSmartSearch={handleSmartSearch}
      handleUntaggedSearch={handleUntaggedSearch}
      logo={logo}
    />
  );
}
