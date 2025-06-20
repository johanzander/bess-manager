// frontend/src/lib/decisionIntelligenceAPI.tsx

import api from './api';
import { FlowPattern, DecisionIntelligenceResponse } from '../types/decisionFramework';

/**
 * Fetches decision intelligence data from the backend
 * @returns Promise<FlowPattern[]> Array of flow patterns for 24 hours
 */
export const fetchDecisionIntelligence = async (): Promise<FlowPattern[]> => {
  try {
    const response = await api.get('/api/decision-intelligence');
    // Backend now returns data in camelCase format
    return response.data.patterns || response.data;
  } catch (error) {
    console.error('Error fetching decision intelligence data:', error);
    throw new Error('Failed to load decision intelligence data');
  }
};

/**
 * Fetches decision intelligence summary data
 * @returns Promise<DecisionIntelligenceResponse> Complete response with patterns and summary
 */
export const fetchDecisionIntelligenceSummary = async (): Promise<DecisionIntelligenceResponse> => {
  try {
    const response = await api.get('/api/decision-intelligence');
    // Backend now returns data in camelCase format
    return response.data;
  } catch (error) {
    console.error('Error fetching decision intelligence summary:', error);
    throw new Error('Failed to load decision intelligence summary');
  }
};