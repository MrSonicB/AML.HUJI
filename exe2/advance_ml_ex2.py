# -*- coding: utf-8 -*-
"""AdvanceML_EX2.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1gMX7OMQHuM6exHKJ0Bq7eLprAG1GGlEV
"""

import torch
from torch import nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset, Subset, Dataset
from tqdm import tqdm

import numpy as np
import matplotlib.pyplot as plt
from torch.optim.lr_scheduler import CosineAnnealingLR
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from matplotlib.colors import Normalize, LinearSegmentedColormap
from matplotlib.cm import ScalarMappable

# Set global variables
DEVICE = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
SEED = 42
LATENT_DIM = 2
BATCH_SIZE = 128
NUM_OF_EPOCH = 20
NORM_FLOW_LR = 1e-3
MATCH_FLOW_LR = 1e-3
EMBEDDING_DIM = 10
NUM_OF_CLASSES = 5
MATCH_FLOW_DELTA_T = 1e-3
NUM_0F_DATA_POINTS = int(25e4)
NUM_OF_AFFINE_LAYERS = 15

# Set Random Seed
torch.manual_seed(SEED)          # Sets the seed for CPU
torch.cuda.manual_seed(SEED)     # Sets the seed for the current GPU

# Initiate distributions
mean = torch.zeros(2).to(DEVICE)
covariance_matrix = torch.eye(2).to(DEVICE)
mvn_dist = torch.distributions.MultivariateNormal(mean, covariance_matrix)

low = torch.tensor(0.0).to(DEVICE)
high = torch.tensor(1.0).to(DEVICE)
uniform_dist = torch.distributions.Uniform(low, high)

"""**Content of create_data file**"""

# region: Conditional Helpers
def generate_points_on_ring(center, radius, thickness, num_points):
    points = []
    while len(points) < num_points:
        r = np.random.uniform(radius - thickness / 2, radius + thickness / 2)
        theta = np.random.uniform(0, 2 * np.pi)
        x = center[0] + r * np.cos(theta)
        y = center[1] + r * np.sin(theta)
        points.append((x, y))
    return points


def sample_olympic_rings(num_points_per_ring, ring_thickness=0.1):
    centers = [(0, 0), (2, 0), (4, 0), (1, -1), (3, -1)]
    colors = ['blue', 'black', 'red', 'yellow', 'green']
    radius = 1
    all_points = []
    all_labels = []

    for center, color in zip(centers, colors):
        points = generate_points_on_ring(center, radius, ring_thickness, num_points_per_ring)
        labels = [color] * num_points_per_ring
        all_points.extend(points)
        all_labels.extend(labels)

    return all_points, all_labels


# endregion: Conditional Helpers

# region: Unconditional Helpers

def point_in_ring(x, y, center, radius, thickness):
    distance = np.sqrt((x - center[0]) ** 2 + (y - center[1]) ** 2)
    return radius - thickness / 2 <= distance <= radius + thickness / 2


def generate_points_on_rings__unconditional(centers, radius, thickness, num_points):
    points = []
    count = 0
    while count < num_points:
        x = np.random.uniform(-1, 5)
        y = np.random.uniform(-2, 1)
        in_any_ring = False
        for center in centers:
            if point_in_ring(x, y, center, radius, thickness):
                in_any_ring = True
                break
        if in_any_ring:
            points.append((x, y))
            count += 1
    return points

# endregion: Unconditional Helpers

def create_olympic_rings(n_points, ring_thickness=0.25, verbose=True):
    num_points_per_ring = n_points // 5
    sampled_points, labels = sample_olympic_rings(num_points_per_ring, ring_thickness)

    # Plotting the points
    if verbose:
        x, y = zip(*sampled_points)
        colors = labels
        if len(sampled_points) > 10000:
            rand_idx = np.random.choice(len(sampled_points), 10000, replace=False)
            plt.scatter(np.array(x)[rand_idx], np.array(y)[rand_idx], s=1, c=np.array(colors)[rand_idx])
        else:
            plt.scatter(x, y, s=1, c=colors)
        plt.gca().set_aspect('equal', adjustable='box')
        plt.title('Numpy Sampled Olympic Rings')
        plt.show()

    sampled_points = np.asarray(sampled_points)
    # transform labels from strings to ints
    label_to_int = {k: v for v, k in enumerate(np.unique(labels))}
    int_to_label = {v: k for k, v in label_to_int.items()}
    labels = np.array([label_to_int[label] for label in labels])

    sampled_points = np.asarray(sampled_points)
    # normalize data
    sampled_points = (sampled_points - np.mean(sampled_points, axis=0)) / np.std(sampled_points, axis=0)

    return sampled_points, labels, int_to_label


def create_unconditional_olympic_rings(n_points, ring_thickness=0.25, verbose=True):
    centers = [(0, 0), (2, 0), (4, 0), (1, -1), (3, -1)]
    radius = 1
    data = generate_points_on_rings__unconditional(centers, radius, ring_thickness, n_points)
    if verbose:
        x, y = zip(*data)
        if len(data) > 10000:
            rand_idx = np.random.choice(len(data), 10000, replace=False)
            plt.scatter(np.array(x)[rand_idx], np.array(y)[rand_idx], s=1)
        else:
            plt.scatter(x, y, s=1)
        plt.gca().set_aspect('equal', adjustable='box')
        plt.title('Numpy Sampled Olympic Rings')
        plt.show()
    data = np.asarray(data)
    # normalize data
    data = (data - np.mean(data, axis=0)) / np.std(data, axis=0)
    return data

"""**Auxiliary functions**"""

def create_conditional_dataloaders(split, num_of_samples=NUM_0F_DATA_POINTS, batch_size=BATCH_SIZE, verbose=False):
    # Crate custom class for Dataset
    class CombinedDataset(Dataset):
        def __init__(self, dataset1, dataset2):
            self.dataset1 = dataset1
            self.dataset2 = dataset2
            assert len(dataset1) == len(dataset2), "Datasets must have the same length"

        def __len__(self):
            return len(self.dataset1)

        def __getitem__(self, idx):
            sample1 = self.dataset1[idx]
            sample2 = self.dataset2[idx]
            return sample1, sample2

    # Get points sample
    sampled_points, labels, int_to_label = create_olympic_rings(n_points=num_of_samples, verbose=verbose)
    sampled_points = sampled_points.astype(np.float32)
    sampled_points = torch.from_numpy(sampled_points)

    labels = labels.astype(np.int32)
    labels = torch.from_numpy(labels)

    # Creata a dataset
    dataset_2d_points = TensorDataset(sampled_points)
    dataset_labels = TensorDataset(labels)

    # Split into two subsets: training and validation according to the split value
    indices = list(range(len(dataset_2d_points)))
    np.random.shuffle(indices)
    split = int(split * len(indices))
    train_indices, val_indices = indices[:split], indices[split:]

    train_subset_2d_points = Subset(dataset_2d_points, train_indices)
    val_subset_2d_points = Subset(dataset_2d_points, val_indices)
    train_subset_labels = Subset(dataset_labels, train_indices)
    val_subset_labels = Subset(dataset_labels, val_indices)

    # Create dataloaders
    train_loader = DataLoader(CombinedDataset(train_subset_2d_points, train_subset_labels), batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(CombinedDataset(val_subset_2d_points, val_subset_labels), batch_size=batch_size, shuffle=False)

    return train_loader, val_loader, int_to_label

def create_unconditional_dataloaders(split, num_of_samples=NUM_0F_DATA_POINTS, batch_size=BATCH_SIZE, verbose=False):
    # Get points sample
    sampled_points = create_unconditional_olympic_rings(n_points=num_of_samples, verbose=verbose)
    sampled_points = sampled_points.astype(np.float32)
    tensor_2d_points = torch.from_numpy(sampled_points)

    # Creata a dataset
    dataset_2d_points = TensorDataset(tensor_2d_points)

    # Split into two subsets: training and validation according to the split value
    indices = list(range(len(dataset_2d_points)))
    np.random.shuffle(indices)
    split = int(split * len(indices))
    train_indices, val_indices = indices[:split], indices[split:]

    train_subset_2d_points = Subset(dataset_2d_points, train_indices)
    val_subset_2d_points = Subset(dataset_2d_points, val_indices)

    # Create dataloaders
    train_loader = DataLoader(train_subset_2d_points, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_subset_2d_points, batch_size=batch_size, shuffle=False)

    return train_loader, val_loader

def compute_gaussian_log_probs(samples_tensor, mean_tensor, var_tensor):
    tensor1 = torch.log(2 * torch.pi * var_tensor)
    tensor2 = torch.pow(samples_tensor - mean_tensor, 2) / var_tensor
    log_probs_vector = -0.5 * torch.sum(tensor1 + tensor2, dim=1)

    return log_probs_vector

def plot_nflow_losses(val_mean_log_probs, val_mean_log_inv_dets):
    # Plot figure of loss as function of fitting iteration
    number_of_epoch = len(val_mean_log_probs)
    mean_losses = [val_mean_log_probs[i] + val_mean_log_inv_dets[i] for i in range(number_of_epoch)]

    epochs_list = list(range(1, number_of_epoch + 1))
    losses_plot = make_subplots(rows=1, cols=1)
    losses_plot.add_trace(
        go.Scatter(x=epochs_list, y=val_mean_log_probs, name='Log Probs', mode='lines+markers', line=dict(color='blue')),
        row=1, col=1
    )
    losses_plot.add_trace(
        go.Scatter(x=epochs_list, y=val_mean_log_inv_dets, name='Log Inv Dets', mode='lines+markers', line=dict(color='green')),
        row=1, col=1
    )
    losses_plot.add_trace(
        go.Scatter(x=epochs_list, y=mean_losses, name='Mean Losses', mode='lines+markers', line=dict(color='red')),
        row=1, col=1
    )
    losses_plot.update_layout(height=600, width=1000,
                                title_text="Validaion mean losses as functions of number of epoch",
                                xaxis_title="Number Of Epoch",
                                yaxis_title="Validaion Mean Loss")
    losses_plot.show()

def plot_match_flow_losses(epoch_mean_losses):
    # Plot match flow training losses as a function of epoch
    epoch_mean_losses = epoch_mean_losses.to('cpu').detach().numpy()
    number_of_epoch = len(epoch_mean_losses)
    epochs_list = list(range(1, number_of_epoch + 1))

    # Create plot
    losses_plot = make_subplots(rows=1, cols=1)
    losses_plot.add_trace(
        go.Scatter(x=epochs_list, y=epoch_mean_losses, name='Log Probs', mode='lines+markers', line=dict(color='blue')),
        row=1, col=1
    )
    losses_plot.update_layout(height=600, width=1000,
                            title_text="Train mean losses as functions of number of epoch",
                            xaxis_title="Number Of Epoch",
                            yaxis_title="Train Mean Loss")
    losses_plot.show()

def plot_2d_samples(samples_list, title_list, colors=[]):
    # If using colore for each point, validate that colors have enough colors
    assert(len(colors) == 0 or len(colors) == samples_list[0].size(0))

    # Create a figure
    number_of_plots = len(samples_list)
    fig, axes = plt.subplots(number_of_plots, 1, figsize=(7, 5 * number_of_plots))

    if number_of_plots == 1:
        axes = [axes]

    # Plot each samples from each time flow
    for index in range(len(samples_list)):
        samples = samples_list[index]
        x = samples[:, 0].to('cpu').detach().numpy()
        y = samples[:, 1].to('cpu').detach().numpy()
        if len(colors) == 0:
            axes[index].scatter(x, y, s=10, c='blue', alpha=0.5)
        else:
            axes[index].scatter(x, y, s=10, c=colors, alpha=0.5)

        axes[index].set_title(title_list[index])
        axes[index].grid(True)

        # Set axis limits
        axes[index].set_xlim(-2.5, 2.5)
        axes[index].set_ylim(-2.5, 2.5)

    # Adjust layout
    plt.tight_layout()

    # Show the plot
    plt.show()

def plot_points_trajectory(samples_tensor, colors_lst=[], inverse=False, use_time=False):
    # Get number of steps of each point
    number_of_points = samples_tensor.size()[0]
    number_of_steps = samples_tensor.size()[1]

    # Validate we color the points according to time or according to the point
    assert(len(colors_lst) == 0 or len(colors_lst) == number_of_points)

    # Create a Norm function and steps linspace
    if use_time:
        norm = Normalize(vmin=0, vmax=1)
        steps = np.linspace(0, 1, number_of_steps)
    else:
        norm = Normalize(vmin=0, vmax=number_of_steps - 1)
        steps = np.linspace(0, number_of_steps-1, number_of_steps)

    if inverse:
        steps = steps[::-1]

    # Create color maps
    default_cmap = plt.get_cmap('Reds')

    # Create a custom yellow colormap
    yellow_cmap = LinearSegmentedColormap.from_list(
        "custom_yellow",
        ["white", "gold", "black"]
    )
    colors_map = {'blue': 'Blues', 'black': 'Greys', 'red': 'Reds', 'green': 'Greens'}
    colors_cmaps = {key: plt.get_cmap(val) for key, val in colors_map.items()}
    colors_cmaps.update({'yellow': yellow_cmap})

    # Create the figure
    if len(colors_lst) == 0:
        fig, ax = plt.subplots(figsize=(8, 6))
    else:
        fig, ax = plt.subplots(figsize=(20, 6))

    title = 'Points Trajectory with diffrent color for each time'
    if inverse:
      title += ' (Inversed)'
    ax.set_title(title)

    for index in range(number_of_points):
        trajectory = samples_tensor[index]
        x = trajectory[:, 0].to('cpu').detach().numpy()
        y = trajectory[:, 1].to('cpu').detach().numpy()
        if len(colors_lst) == 0:
            ax.scatter(x, y, s=100, c=default_cmap(norm(steps)))
            ax.plot(x, y)
        else:
            cmap = colors_cmaps[colors_lst[index]]
            ax.scatter(x, y, s=100, c=cmap(norm(steps)))

    # Add colorbar
    bar_title = 'Time' if use_time else 'Steps'
    if len(colors_lst) == 0:
        sm = ScalarMappable(cmap=default_cmap, norm=norm)
        sm.set_array([])
        cbar = plt.colorbar(sm)
        cbar.set_label(bar_title)
    else:
        for cmap in colors_cmaps.values():
            sm = ScalarMappable(cmap=cmap, norm=norm)
            sm.set_array([])
            cbar = plt.colorbar(sm)
            cbar.set_label(bar_title)

    ax.legend()
    plt.show()

"""**Part1: Normalization Flow**"""

class AffineCouplingLayer(nn.Module):
    def __init__(self, latent_dim):
        super(AffineCouplingLayer, self).__init__()

        self.left_dim = round(latent_dim / 2)
        self.right_dim = LATENT_DIM - self.left_dim

        self.compute_log_s = nn.Sequential(
            nn.Linear(self.left_dim, 8),
            nn.LeakyReLU(),
            nn.Linear(8, 8),
            nn.LeakyReLU(),
            nn.Linear(8, 8),
            nn.LeakyReLU(),
            nn.Linear(8, 8),
            nn.LeakyReLU(),
            nn.Linear(8, self.right_dim)
        )

        self.compute_b = nn.Sequential(
            nn.Linear(self.left_dim, 8),
            nn.LeakyReLU(),
            nn.Linear(8, 8),
            nn.LeakyReLU(),
            nn.Linear(8, 8),
            nn.LeakyReLU(),
            nn.Linear(8, 8),
            nn.LeakyReLU(),
            nn.Linear(8, self.right_dim)
        )

    def forward(self, z):
        z_left = z[:, :self.left_dim]
        z_right = z[:, self.left_dim:]

        log_s_vals = self.compute_log_s(z_left)
        b_vals = self.compute_b(z_left)

        z_new_right = torch.exp(log_s_vals) * z_right + b_vals
        z_new = torch.cat([z_left, z_new_right], dim=1)
        return z_new

    def inverse(self, y):
        y_left = y[:, :self.left_dim]
        y_right = y[:, self.left_dim:]

        # We assume that y_left = x_lest, therefore we can us it to compute the values of log s and b
        log_s_vals = self.compute_log_s(y_left)
        b_vals = self.compute_b(y_left)

        y_new_right = (1 / torch.exp(log_s_vals)) * (y_right - b_vals)
        y_new = torch.cat([y_left, y_new_right], dim=1)
        return y_new

    def log_inverse_jacobian_det(self, y):
        y_left = y[:, :self.left_dim]

        # We assume that y_left = x_lest, therefore we can us it to compute the value of log s
        log_s_vals = self.compute_log_s(y_left)

        # Log determinant of jacobian of inverse patrix is exactly minus the sun of log_s values
        log_inverse_jacobian_det = -1 * log_s_vals.sum(dim=1, keepdim=True)
        return log_inverse_jacobian_det


class PermutationLayer(nn.Module):
    def __init__(self, permutation):
        super(PermutationLayer, self).__init__()
        self.register_buffer('permutation', permutation)
        self.register_buffer('inverse_permutation', torch.argsort(permutation))

    def forward(self, x):
        x = x[:, self.permutation]
        return x

    def inverse(self, x):
        x = x[:, self.inverse_permutation]
        return x


class NormalizationFlow(nn.Module):
    def __init__(self, latent_dim=LATENT_DIM, num_layers=NUM_OF_AFFINE_LAYERS):
        super(NormalizationFlow, self).__init__()
        self.layers = nn.ModuleList()

        for i in range(num_layers - 1):
            self.layers.append(AffineCouplingLayer(latent_dim))
            permutation = torch.randperm(latent_dim)
            self.layers.append(PermutationLayer(permutation))

        # Append the last affine coupling layer
        self.layers.append(AffineCouplingLayer(latent_dim))

    def forward(self, z):
        for layer in self.layers:
            z = layer(z)

        return z

    def get_inverse_and_log_inverse_jacobian_det(self, y):
        log_inverse_jacobian_det = 0
        for layer in reversed(self.layers):
            # Ignoring permutation layers
            if isinstance(layer, AffineCouplingLayer):
                det = layer.log_inverse_jacobian_det(y)
                log_inverse_jacobian_det += det

            y = layer.inverse(y)

        return y, log_inverse_jacobian_det

def evaluate_nflow_model(nflow_model, val_loader):
    with torch.no_grad():
        # Set model with evaluation mode
        nflow_model.eval()

        # Initiate val variables
        mean_val_epoch_log_probs = 0.
        mean_val_epoch_log_inv_det = 0.
        number_of_seen_samples = 0

        for batch in tqdm(val_loader):
            # Extract batch from device and move it to DEVIE
            batch = batch[0]
            batch = batch.to(DEVICE)

            # Compute inverse transformation and log_inverse_det for each point in the batch
            batch_inverse, log_inverse_det = nflow_model.get_inverse_and_log_inverse_jacobian_det(batch)

            # Compute PDF of Normal Gaussian for each point in the batch_inverse
            batch_size = batch.size()[0]
            batch_log_probs = compute_gaussian_log_probs(samples_tensor=batch_inverse, mean_tensor=torch.zeros(batch_size, LATENT_DIM).to(DEVICE),
                                              var_tensor=torch.ones(batch_size, LATENT_DIM).to(DEVICE)).unsqueeze(dim=1)

            # Compute the mean of the two loss component
            mean_batch_log_inverse_det = -1 * log_inverse_det.mean().item()
            mean_batch_log_probs = -1 * batch_log_probs.mean().item()

            # Update epoch mean losses
            batch_size = batch.size()[0]
            mean_val_epoch_log_probs = (mean_val_epoch_log_probs * number_of_seen_samples + mean_batch_log_probs * batch_size) / (number_of_seen_samples + batch_size)
            mean_val_epoch_log_inv_det = (mean_val_epoch_log_inv_det * number_of_seen_samples + mean_batch_log_inverse_det * batch_size) / (number_of_seen_samples + batch_size)

            # Update number of seen samples
            number_of_seen_samples += batch_size

        return mean_val_epoch_log_probs, mean_val_epoch_log_inv_det

def train_normalization_flow(train_loader, val_loader, num_epochs=NUM_OF_EPOCH, lr=NORM_FLOW_LR):
    nflow_model = NormalizationFlow()
    nflow_model = nflow_model.to(DEVICE)
    optimizer = optim.Adam(nflow_model.parameters(), lr=lr)
    scheduler = CosineAnnealingLR(optimizer, T_max=num_epochs)

    val_mean_log_probs = []
    val_mean_log_inv_dets = []

    for epoch in range(num_epochs):
        # Set model with training mode
        nflow_model.train()

        for batch in tqdm(train_loader):
            # Extract batch from device and move it to DEVIE
            batch = batch[0]
            batch = batch.to(DEVICE)

            # Zero the parameter gradients
            optimizer.zero_grad()

            # Compute inverse transformation and log_inverse_det for each point in the batch
            batch_inverse, log_inverse_det = nflow_model.get_inverse_and_log_inverse_jacobian_det(batch)

            # Compute PDF of Normal Gaussian for each point in the batch_inverse
            batch_size = batch.size()[0]
            batch_log_probs = compute_gaussian_log_probs(samples_tensor=batch_inverse, mean_tensor=torch.zeros(batch_size, LATENT_DIM).to(DEVICE),
                                                     var_tensor=torch.ones(batch_size, LATENT_DIM).to(DEVICE)).unsqueeze(dim=1)

            # Compute loss according to MLE
            mean_batch_loss = -1 * (batch_log_probs + log_inverse_det).mean()

            # Backpropargate and update the model's wights
            mean_batch_loss.backward()
            optimizer.step()

        # Evaluate model on the validation set
        mean_val_epoch_log_probs, mean_val_epoch_log_inv_det = evaluate_nflow_model(nflow_model, val_loader)
        val_mean_log_probs.append(mean_val_epoch_log_probs)
        val_mean_log_inv_dets.append(mean_val_epoch_log_inv_det)

        # Take step in scheduler
        scheduler.step()

    # Set model with evaluation mode
    nflow_model.eval()

    return nflow_model, val_mean_log_probs, val_mean_log_inv_dets

train_loader, val_loader = create_unconditional_dataloaders(split=0.96, batch_size=256)
nflow_model, val_mean_log_probs, val_mean_log_inv_dets = train_normalization_flow(train_loader=train_loader, val_loader=val_loader)

# Question 1
plot_nflow_losses(val_mean_log_probs, val_mean_log_inv_dets)

# Question 2
seeds = [38, 56, 67]
samples_list = []
title_list = []
for seed in seeds:
    torch.manual_seed(seed)
    samples = mvn_dist.sample((1000,)).to(DEVICE)
    new_points = nflow_model(samples)
    samples_list.append(new_points)
    title_list.append(f"Seed {seed}")

plot_2d_samples(samples_list, title_list)

# Question 3
torch.manual_seed(SEED)
samples = mvn_dist.sample((1000,)).to(DEVICE)
samples_list = [samples]
title_list = ["Time step 0"]

for index in range(len(nflow_model.layers)):
    layer = nflow_model.layers[index]
    samples = layer(samples)
    if isinstance(layer, AffineCouplingLayer):
        if index % 6 == 4:
            samples_list.append(samples)
            title_list.append(f"Time step {int(index/2) + 1}")

plot_2d_samples(samples_list, title_list)

# Question 4
torch.manual_seed(SEED)
samples = mvn_dist.sample((10,)).to(DEVICE)
samples_tensor = samples.unsqueeze(0)

for layer in nflow_model.layers:
    samples = layer(samples)
    if isinstance(layer, AffineCouplingLayer):
        samples_tensor = torch.cat([samples_tensor, samples.unsqueeze(0)], dim=0)


samples_tensor = samples_tensor.transpose(0, 1)
plot_points_trajectory(samples_tensor)

# Question 5
# Sample 3 point from the target distrebution and 2 outside the target distribution
# Those points will be also used in Q5 of the part Match Flow
n_inside = 3
n_outside = 2
inside_points_org = torch.tensor([[-0.75, 0.], [0.75, 0.], [0, -1.]]).to(DEVICE)
outside_points_org = torch.tensor([[-0.5, 2.], [0.5, 2.]]).to(DEVICE)

# Compute the inverse trajectory of the selected points - Normalization Flow
inside_points = inside_points_org
outside_points = outside_points_org
inside_tensor = inside_points.unsqueeze(0)
outside_tensor = outside_points.unsqueeze(0)

for layer in reversed(nflow_model.layers):
    inside_points = layer.inverse(inside_points)
    outside_points = layer.inverse(outside_points)
    if isinstance(layer, AffineCouplingLayer):
        inside_tensor = torch.cat([inside_tensor, inside_points.unsqueeze(0)], dim=0)
        outside_tensor = torch.cat([outside_tensor, outside_points.unsqueeze(0)], dim=0)

inside_tensor = inside_tensor.transpose(0, 1)
outside_tensor = outside_tensor.transpose(0, 1)

# Compute the log probabilities of the selected samples
batch = torch.cat([inside_points_org, outside_points_org], dim=0)
batch_inverse, log_inverse_det = nflow_model.get_inverse_and_log_inverse_jacobian_det(batch)

# Compute PDF of Normal Gaussian for each point in the batch_inverse
batch_size = batch.size()[0]
batch_log_probs = compute_gaussian_log_probs(samples_tensor=batch_inverse, mean_tensor=torch.zeros(batch_size, LATENT_DIM).to(DEVICE),
                                          var_tensor=torch.ones(batch_size, LATENT_DIM).to(DEVICE)).unsqueeze(dim=1)
log_probs = batch_log_probs + log_inverse_det

# Present inverse trajectory and log probabilities of the selected three points inside the target distrebution
print("\nThree points inside the olympic logo:")
for i in range(n_inside):
    print(f"\tPoint {i + 1}: ({batch[i, 0].item():.2f}, {batch[i, 1].item():.2f}): Log Prob: {log_probs[i].item():.2f}")

print("\n Trajectories:")
plot_points_trajectory(inside_tensor, inverse=True)

# Present inverse trajectory and log probabilities of the selected two points outside the target distrebution
print("\nTwo points outside the olympic logo:")
for i in range(n_outside):
    print(f"\tPoint {i + 1}: ({batch[i + n_inside, 0].item():.2f}, {batch[i + n_inside, 1].item():.2f}): Log Prob: {log_probs[i + n_inside].item():.2f}")

print("\n Trajectories:")
plot_points_trajectory(outside_tensor, inverse=True)

"""Part 2: Flow Matching

**Unconditional Flow Matching**
"""

class UnconditionalVF(nn.Module):
    def __init__(self, latent_dim):
        super(UnconditionalVF, self).__init__()
        self.compute_derivative = nn.Sequential(
            nn.Linear(latent_dim + 1, 64),
            nn.LeakyReLU(),
            nn.Linear(64, 64),
            nn.LeakyReLU(),
            nn.Linear(64, 64),
            nn.LeakyReLU(),
            nn.Linear(64, 64),
            nn.LeakyReLU(),
            nn.Linear(64, latent_dim)
        )

    def forward(self, y, t):
        # Concatenate prior samples and time into input tensor
        inputs = torch.cat([y, t], dim=1)

        # Pass to neural network and return predicted derivatives
        output = self.compute_derivative(inputs)
        return output

def train_unconditional_VF(train_loader, num_epochs=NUM_OF_EPOCH, lr=MATCH_FLOW_LR):
    # Initiate Unconditional Vector Field model and move its parameters to DEVICE
    uncon_vf = UnconditionalVF(latent_dim=LATENT_DIM)
    uncon_vf = uncon_vf.to(DEVICE)

    # Initiate ADAM optimizer and Cosine scheduler
    optimizer = optim.Adam(uncon_vf.parameters(), lr=lr)
    scheduler = CosineAnnealingLR(optimizer, T_max=num_epochs)

    epoch_mean_losses = []
    for epoch in range(num_epochs):
        # Set model with training mode
        uncon_vf.train()
        # Initiate variables
        mean_epoch_loss = 0.
        number_of_seen_samples = 0

        # Iterate over the dataset
        for batch in tqdm(train_loader):
            # Extract batch from device and move it to DEVICE
            batch = batch[0]
            batch = batch.to(DEVICE)
            batch_size = batch.size()[0]

            # Sample corresponding vectors from standard Gaussian distribution
            noised_samples = mvn_dist.sample((batch_size,)).to(DEVICE)

            # Sample time from Uniform distribution of 0 to 1
            time = uniform_dist.sample((batch_size,)).unsqueeze(dim=1).to(DEVICE)

            # Compute noised vectors at time t according to optimal path with
            # respect to each point in the batch
            y_batch = (1 - time) * noised_samples + time * batch

            # Zero the parameter gradients
            optimizer.zero_grad()

            # Compute the unconditional derivatives
            uncon_der_batch = uncon_vf(y_batch, time)

            # Compute the mean loss
            con_der_batch = batch - noised_samples
            batch_losses = torch.sum(torch.pow(uncon_der_batch - con_der_batch, 2), dim=1, keepdim=True)
            mean_batch_loss = batch_losses.mean()

            # Backpropargate and update the model's wights
            mean_batch_loss.backward()
            optimizer.step()

            # Update variables
            with torch.no_grad():
                mean_epoch_loss = (mean_epoch_loss * number_of_seen_samples + mean_batch_loss.item() * batch_size) / (number_of_seen_samples + batch_size)
                number_of_seen_samples += batch_size

        # Update the epoch losses list and take a step in the scheduler
        epoch_mean_losses.append(mean_epoch_loss)
        scheduler.step()

    # Move model's mode to evaluation
    uncon_vf.eval()
    return uncon_vf, epoch_mean_losses

train_loader, _ = create_unconditional_dataloaders(split=1, verbose=True)
uncon_vf, epoch_mean_losses = train_unconditional_VF(train_loader=train_loader)

# Question 1
plot_match_flow_losses(torch.tensor(epoch_mean_losses))

# Question 2
num_of_samples = 1000
samples = mvn_dist.sample((num_of_samples, )).to(DEVICE)
selected_time_list = [0, 0.2, 0.4, 0.6, 0.8, 1]
samples_list = [samples]
title_list = ["Time 0"]

for time in np.linspace(0, 1 - MATCH_FLOW_DELTA_T, 1000):
    time_vec = time * torch.ones(num_of_samples, 1).to(DEVICE)
    samples = samples + uncon_vf(samples, time_vec) * MATCH_FLOW_DELTA_T
    new_time = time + MATCH_FLOW_DELTA_T
    if new_time in selected_time_list:
        samples_list.append(samples)
        title_list.append(f"Time {new_time}")

plot_2d_samples(samples_list, title_list)

# Question 3
num_of_samples = 10
samples = mvn_dist.sample((num_of_samples, )).to(DEVICE)
samples_tensor = samples.unsqueeze(0)

for time in np.linspace(0, 1 - MATCH_FLOW_DELTA_T, 1000):
    time_vec = time * torch.ones(num_of_samples, 1).to(DEVICE)
    samples = samples + uncon_vf(samples, time_vec) * MATCH_FLOW_DELTA_T
    samples_tensor = torch.cat([samples_tensor, samples.unsqueeze(0)], dim=0)

samples_tensor = samples_tensor.transpose(0, 1)
plot_points_trajectory(samples_tensor, use_time=True)

# Question 4
num_of_samples = 1000
sigma_t_list = [0.002, 0.02, 0.05, 0.1, 0.2]
samples_at_time_1 = []
title_list = []

for sigma_t in sigma_t_list:
    samples = mvn_dist.sample((num_of_samples, )).to(DEVICE)
    for time in np.linspace(0, 1 - sigma_t, int(1/sigma_t)):
        time_vec = time * torch.ones(num_of_samples, 1).to(DEVICE)
        samples = samples + uncon_vf(samples, time_vec) * MATCH_FLOW_DELTA_T


    samples_at_time_1.append(samples)
    title_list.append(f"Smples at time 1 with delta time of: {sigma_t}")

plot_2d_samples(samples_at_time_1, title_list)

# Compute the inverse trajectory of the selected points - Flow Matching
inside_points = inside_points_org
outside_points = outside_points_org
inside_tensor = inside_points.unsqueeze(0)
outside_tensor = outside_points.unsqueeze(0)

for time in np.linspace(1, MATCH_FLOW_DELTA_T, 1000):
    time_inside_vec = time * torch.ones(n_inside, 1).to(DEVICE)
    inside_points = inside_points - uncon_vf(inside_points, time_inside_vec) * MATCH_FLOW_DELTA_T

    time_outside_vec = time * torch.ones(n_outside, 1).to(DEVICE)
    outside_points = outside_points - uncon_vf(outside_points, time_outside_vec) * MATCH_FLOW_DELTA_T

    # Update tensors with the new points at the new time
    inside_tensor = torch.cat([inside_tensor, inside_points.unsqueeze(0)], dim=0)
    outside_tensor = torch.cat([outside_tensor, outside_points.unsqueeze(0)], dim=0)

# Plot inverse trajectory of the three points inside the target distrebution
print("\nThree points inside the olympic logo:")
inside_tensor = inside_tensor.transpose(0, 1)
plot_points_trajectory(inside_tensor, inverse=True, use_time=True)

# Plot inverse trajectory of the two points outside the target distrebution
print("\nTwo points outside the olympic logo:")
outside_tensor = outside_tensor.transpose(0, 1)
plot_points_trajectory(outside_tensor, inverse=True, use_time=True)

"""**Conditional Flow Matching**"""

class EmbeddedUnconditionalVF(nn.Module):
    def __init__(self, latent_dim, num_of_class, embedding_dim):
        super(EmbeddedUnconditionalVF, self).__init__()
        self.embedding = nn.Embedding(num_of_class, embedding_dim)
        self.compute_derivative = nn.Sequential(
            nn.Linear(latent_dim + embedding_dim + 1, 64),
            nn.LeakyReLU(),
            nn.Linear(64, 64),
            nn.LeakyReLU(),
            nn.Linear(64, 64),
            nn.LeakyReLU(),
            nn.Linear(64, 64),
            nn.LeakyReLU(),
            nn.Linear(64, latent_dim)
        )

    def forward(self, y, c, t):
        # Compute embedding of class tensor
        embedded_vec = self.embedding(c)

        # Concatenate prior samples, embedding and time into input tensor
        inputs = torch.cat([y, embedded_vec, t], dim=1)

        # Pass to neural network and return predicted derivatives
        output = self.compute_derivative(inputs)
        return output

def train_embedded_unconditional_VF(train_loader, num_epochs=NUM_OF_EPOCH, lr=MATCH_FLOW_LR):
    # Initiate Unconditional Vector Field model and move its parameters to DEVICE
    emb_uncon_vf = EmbeddedUnconditionalVF(latent_dim=LATENT_DIM, num_of_class=NUM_OF_CLASSES, embedding_dim=EMBEDDING_DIM)
    emb_uncon_vf = emb_uncon_vf.to(DEVICE)

    # Initiate ADAM optimizer and Cosine scheduler
    optimizer = optim.Adam(emb_uncon_vf.parameters(), lr=lr)
    scheduler = CosineAnnealingLR(optimizer, T_max=num_epochs)

    epoch_mean_losses = []
    for epoch in range(num_epochs):
        # Set model with training mode
        emb_uncon_vf.train()
        # Initiate variables
        mean_epoch_loss = 0.
        number_of_seen_samples = 0

        # Iterate over the dataset
        for batch_sample, batch_class in tqdm(train_loader):
            # Extract batchs from device and move it to DEVICE
            batch_sample = batch_sample[0]
            batch_class = batch_class[0]
            batch_sample = batch_sample.to(DEVICE)
            batch_class = batch_class.to(DEVICE)
            batch_size = batch_sample.size()[0]

            # Sample corresponding vectors from standard Gaussian distribution
            noised_samples = mvn_dist.sample((batch_size,)).to(DEVICE)

            # Sample time from Uniform distribution of 0 to 1
            time = uniform_dist.sample((batch_size,)).unsqueeze(dim=1).to(DEVICE)

            # Compute noised vectors at time t according to optimal path with
            # respect to each point in the batch
            y_batch = (1 - time) * noised_samples + time * batch_sample

            # Zero the parameter gradients
            optimizer.zero_grad()

            # Compute the unconditional derivatives
            uncon_der_batch = emb_uncon_vf(y_batch, batch_class, time)

            # Compute the mean loss
            con_der_batch = batch_sample - noised_samples
            batch_losses = torch.sum(torch.pow(uncon_der_batch - con_der_batch, 2), dim=1, keepdim=True)
            mean_batch_loss = batch_losses.mean()

            # Backpropargate and update the model's wights
            mean_batch_loss.backward()
            optimizer.step()

            # Update variables
            with torch.no_grad():
                mean_epoch_loss = (mean_epoch_loss * number_of_seen_samples + mean_batch_loss.item() * batch_size) / (number_of_seen_samples + batch_size)
                number_of_seen_samples += batch_size

        # Update the epoch losses list and take a step in the scheduler
        epoch_mean_losses.append(mean_epoch_loss)
        scheduler.step()

    # Move model's mode to evaluation
    emb_uncon_vf.eval()
    return emb_uncon_vf, epoch_mean_losses

# Question 1 + Train the model
train_loader, _, int_to_label = create_conditional_dataloaders(split=1, verbose=True)
emb_uncon_vf, epoch_mean_losses = train_embedded_unconditional_VF(train_loader=train_loader)

# Plot Losses (Not asked)
plot_match_flow_losses(torch.tensor(epoch_mean_losses))

# Question 2
num_of_samples = len(int_to_label.keys())
samples =  mvn_dist.sample((num_of_samples, )).to(DEVICE)
colors_indices = list(int_to_label.keys())
classes = torch.tensor(colors_indices).to(DEVICE)
samples_tensor = samples.unsqueeze(0)

for time in np.linspace(0, 1 - MATCH_FLOW_DELTA_T, 1000):
    time_vec = time * torch.ones(num_of_samples, 1).to(DEVICE)
    samples = samples + emb_uncon_vf(samples, classes, time_vec) * MATCH_FLOW_DELTA_T
    samples_tensor = torch.cat([samples_tensor, samples.unsqueeze(0)], dim=0)

samples_tensor = samples_tensor.transpose(0, 1)
colors = [int_to_label[c] for c in colors_indices]
plot_points_trajectory(samples_tensor, colors_lst=colors, use_time=True)

# Question 3
num_of_samples = 3000
samples = mvn_dist.sample((num_of_samples, )).to(DEVICE)
classes = torch.from_numpy(np.random.choice(list(int_to_label.keys()), size=num_of_samples)).to(DEVICE)
color_name_map = {'blue': 'b', 'black': 'k', 'red': 'r', 'yellow': 'y', 'green': 'g'}


for time in np.linspace(0, 1 - MATCH_FLOW_DELTA_T, 1000):
    time_vec = time * torch.ones(num_of_samples, 1).to(DEVICE)
    samples = samples + emb_uncon_vf(samples, classes, time_vec) * MATCH_FLOW_DELTA_T

samples_list = [samples]
colors = [color_name_map[int_to_label[c]] for c in classes.tolist()]
title_list = ["Plot of 3000 points at time 1"]
plot_2d_samples(samples_list, title_list, colors)