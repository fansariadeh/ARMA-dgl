import torch
import torch.nn as nn
import torch.nn.functional as F
import dgl
import dgl.function as fn

from dgl.nn.pytorch.glob import AvgPooling

class ARMAConv(nn.Module):
    def __init__(self,
                 in_dim,
                 out_dim,
                 num_stacks,
                 num_layers,
                 activation=None,
                 dropout=0.0,
                 bias=True):
        super(ARMAConv, self).__init__()
        
        self.in_dim = in_dim
        self.out_dim = out_dim
        self.K = num_stacks
        self.T = num_layers
        self.activation = activation
        self.dropout = nn.Dropout(p=dropout)

        # init weight
        self.w_0 = nn.ModuleDict({
            str(k): nn.Linear(in_dim, out_dim, bias=bias) for k in range(self.K)
        })
        # deeper weight
        self.w = nn.ModuleDict({
            str(k): nn.Linear(out_dim, out_dim, bias=bias) for k in range(self.K)
        })
        # v
        self.v = nn.ModuleDict({
            str(k): nn.Linear(in_dim, out_dim, bias=bias) for k in range(self.K)
        })

    def forward(self, g, feats):
        with g.local_scope():
            init_feats = feats
            # assume that the graphs are undirected and graph.in_degrees() is the same as graph.out_degrees()
            degs = g.in_degrees().float().clamp(min=1)
            norm = torch.pow(degs, -0.5).to(feats.device).unsqueeze(1)
            output = None
            for k in range(self.K):
                feats = init_feats
                for t in range(self.T):
                    feats = feats * norm
                    g.ndata['h'] = feats
                    g.update_all(fn.copy_u('h', 'm'), fn.sum('m', 'h'))
                    feats = g.ndata.pop('h')
                    feats = feats * norm
                    if t == 0:
                        feats = self.w_0[str(k)](feats)
                    else:
                        feats = self.w[str(k)](feats)
                    feats += self.dropout(self.v[str(k)](init_feats))
                    if self.activation is not None:
                        feats = self.activation(feats)
                if output is None:
                    output = feats
                else:
                    output += feats
            return output / self.K 

class ARMA4NC(nn.Module):
    def __init__(self,
                 in_dim,
                 hid_dim,
                 out_dim,
                 num_stacks,
                 num_layers,
                 activation=None,
                 dropout=0.0):
        super(ARMA4NC, self).__init__()

        self.conv1 = ARMAConv(in_dim=in_dim,
                              out_dim=hid_dim,
                              num_stacks=num_stacks,
                              num_layers=num_layers,
                              activation=activation,
                              dropout=dropout)

        self.conv2 = ARMAConv(in_dim=hid_dim,
                              out_dim=out_dim,
                              num_stacks=num_stacks,
                              num_layers=num_layers,
                              activation=activation,
                              dropout=dropout)
        
        self.dropout = nn.Dropout(p=dropout)

    def forward(self, g, feats):
        feats = F.relu(self.conv1(g, feats))
        feats = self.dropout(feats)
        feats = self.conv2(g, feats)
        return feats

class ARMA4GC(nn.Module):
    def __init__(self,
                 in_dim,
                 hid_dim,
                 out_dim,
                 num_stacks,
                 num_layers,
                 activation=None,
                 dropout=0.0):
        super(ARMA4GC, self).__init__()

        self.conv1 = ARMAConv(in_dim=in_dim,
                              out_dim=hid_dim,
                              num_stacks=num_stacks,
                              num_layers=num_layers,
                              activation=activation,
                              dropout=dropout)
        
        self.conv2 = ARMAConv(in_dim=hid_dim,
                              out_dim=hid_dim,
                              num_stacks=num_stacks,
                              num_layers=num_layers,
                              activation=activation,
                              dropout=dropout)
        
        self.conv3 = ARMAConv(in_dim=hid_dim,
                              out_dim=hid_dim,
                              num_stacks=num_stacks,
                              num_layers=num_layers,
                              activation=activation,
                              dropout=dropout)
        
        self.pool = AvgPooling()
        self.dropout = nn.Dropout(p=dropout)
        self.fc = nn.Linear(hid_dim, out_dim)

    def forward(self, g, feats):
        feats = F.relu(self.conv1(g, feats))
        feats = self.dropout(feats)
        feats = F.relu(self.conv2(g, feats))
        feats = self.dropout(feats)
        feats = F.relu(self.conv3(g, feats))
        feats = self.dropout(feats)
        feats = F.relu(self.pool(g, feats))
        feats = self.dropout(feats)
        return self.fc(feats)