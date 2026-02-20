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
    Autonomous ESTI Agent with Online Learning Adaptation.
    Refined on 10-Day Pre-training + Real-time Gradient Descent.
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

        # 1. Decode & Load Model
        buffer = io.BytesIO(base64.b64decode(self.B64_WEIGHTS))
        checkpoint = torch.load(buffer, weights_only=False, map_location='cpu')
        
        self.policy = ESTIPolicy(state_dim=50, hidden_dim=64)
        self.policy.load_state_dict(checkpoint['policy_state_dict'])
        
        # 2. Setup Online Learning
        self.policy.train() # Enable gradients
        self.optimizer = torch.optim.Adam(self.policy.parameters(), lr=5e-5)
        self.last_action_log_prob = None
        self.last_price = {{}}
        self.last_action = None
        
        self.Log(f"🧠 Online Learning Enabled | ID: {{checkpoint['agent_id']}} | Sharpe: {{checkpoint['sharpe']:.2f}}")
        
        self.state_dim = 50

    def calculate_features(self, symbol):
        history = self.History(symbol, 100)
        if not history or len(history) < 50: return None
        
        df = pd.DataFrame([{{'close': t.Price, 'volume': t.Volume}} for t in history])
        df['returns'] = df['close'].pct_change()
        df['sma_20'] = df['close'].rolling(20).mean()
        
        df.fillna(0, inplace=True)
        vals = df.iloc[-1].values
        state = np.pad(vals, (0, max(0, 50 - len(vals))), 'constant')[:50]
        return torch.FloatTensor(state).unsqueeze(0)

    def OnData(self, data):
        for symbol in self.symbols:
            if not data.ContainsKey(symbol): continue
            current_price = data[symbol].Price
            
            # --- 1. Online Adaptation (Reinforce Step) ---
            if self.last_action_log_prob is not None and symbol in self.last_price:
                # Calculate Reward: simple price change delta
                price_change = (current_price - self.last_price[symbol]) / self.last_price[symbol]
                # Reward is positive if price went up and we bought, or down and we sold/held
                # 0 = Buy/Long, 1 = Neutral/Exit
                reward = price_change if self.last_action == 0 else -price_change
                
                # REINFORCE loss: -log_prob * reward
                self.optimizer.zero_grad()
                loss = -self.last_action_log_prob * reward
                loss.backward()
                self.optimizer.step()
                
                if self.Time.minute % 30 == 0: # Log every 30 mins
                    self.Log(f"🧬 Online Learning Step | Syncing weights... | Reward: {{reward:.5f}}")

            # --- 2. Inference ---
            state_tensor = self.calculate_features(symbol)
            if state_tensor is None: continue
            
            # We track gradients for the next update step
            action_probs = self.policy(state_tensor)
            
            # Categorical sampling for exploration/adaptation
            m = torch.distributions.Categorical(action_probs)
            action = m.sample()
            
            self.last_action_log_prob = m.log_prob(action)
            self.last_action = action.item()
            self.last_price[symbol] = current_price
            
            # Action Execution
            if self.last_action == 0 and action_probs[0][0] > 0.6:
                self.SetHoldings(symbol, 0.5)
            elif self.last_action == 1:
                self.SetHoldings(symbol, 0.0)
"""
