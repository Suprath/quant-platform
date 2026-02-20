STRATEGY_TEMPLATE = """
import base64
import io
import torch
import numpy as np
import pandas as pd
from datetime import datetime
from strategy_runtime.base_strategy import BaseStrategy
from strategy_runtime.data_types import Resolution

# ESTI Models definition injected explicitly to avoid cross-module dependency hell
import torch.nn as nn

class ESTIPolicy(nn.Module):
    def __init__(self, state_dim=50, hidden_dim=64):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim, hidden_dim * 2),
            nn.LayerNorm(hidden_dim * 2),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
        )
        self.actor = nn.Sequential(
            nn.Linear(hidden_dim, 32),
            nn.ReLU(),
            nn.Linear(32, 2) # [Hold/Buy, Sell]
        )
    def forward(self, state):
        x = self.net(state)
        logits = self.actor(x)
        return torch.softmax(logits, dim=-1)

class AutonomousESTI(BaseStrategy):
    \"\"\"
    Autonomous ETSI-Generated Strategy.
    Regime Adapted: 15-Day Lookback.
    \"\"\"

    def Initialize(self):
        # Base64 Parameters (Injected by Coordinator)
        self.B64_WEIGHTS = \"\"\"{b64_weights}\"\"\"
        
        # Hyperparameters
        self.SetStartingCash(100000.0)
        self.SetResolution(Resolution.MINUTE)
        
        self.symbols = {symbols_list}
        for s in self.symbols:
            self.AddEquity(s)

        # 1. Decode Weights
        buffer = io.BytesIO(base64.b64decode(self.B64_WEIGHTS))
        checkpoint = torch.load(buffer, weights_only=False, map_location='cpu')
        
        # 2. Re-instantiate Policy
        self.policy = ESTIPolicy(state_dim=50, hidden_dim=64)
        self.policy.load_state_dict(checkpoint['policy_state_dict'])
        self.policy.eval() # Freeze weights

        self.Log(f"🤖 Autonomous ESTI Agent Loaded | ID: {{checkpoint['agent_id']}} | Sharpe: {{checkpoint['sharpe']:.2f}}")
        
        # Local Feature Cache (Requires 50 state_dim)
        self.history_cache = {{}}
        self.state_dim = 50

    def calculate_features(self, symbol):
        # A lightweight version of ESTI FeatureEngineering for realtime inference
        history = self.History(symbol, 200) # Fetch last 200 ticks
        if not history or len(history) < 50: return None
        
        df = pd.DataFrame([{{'close': t.Price, 'volume': t.Volume}} for t in history])
        # Add basic momentum triggers
        df['returns'] = df['close'].pct_change()
        df['sma_20'] = df['close'].rolling(20).mean()
        df['sma_50'] = df['close'].rolling(50).mean()
        
        df.fillna(0, inplace=True)
        # Flatten last row into 50-dim float array (Mock approximation)
        vals = df.iloc[-1].values
        state = np.pad(vals, (0, max(0, 50 - len(vals))), 'constant')[:50]
        return torch.FloatTensor(state).unsqueeze(0)

    def OnData(self, data):
        for symbol in self.symbols:
            if not data.ContainsKey(symbol): continue
            
            # Predict
            state_tensor = self.calculate_features(symbol)
            if state_tensor is None: continue
            
            with torch.no_grad():
                action_probs = self.policy(state_tensor)
                buy_prob = action_probs[0][0].item()
                sell_prob = action_probs[0][1].item()
            
            # Action (Aggressive Thresholds for execution)
            if buy_prob > 0.65:
                # 30% sizing
                self.SetHoldings(symbol, 0.3)
                self.Log(f"📈 AI Entry Signal: {{symbol}} (Confidence: {{buy_prob:.2f}})")
            elif sell_prob > 0.65:
                self.SetHoldings(symbol, 0.0)
                self.Log(f"📉 AI Exit Signal: {{symbol}} (Confidence: {{sell_prob:.2f}})")
"""
