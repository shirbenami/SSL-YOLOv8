import torch
import torch.nn as nn
import torchvision.models as models
from lightly.models.modules.heads import SimCLRProjectionHead
from ultralytics.nn.modules import Conv
from ultralytics import YOLO
from torch.utils.data import DataLoader, Dataset
import torch.nn.init as init
from loss_functions.info_nce import InfoNCE
import os
from torchvision.transforms import functional as F
from torchvision import transforms
from PIL import Image
from torch.utils.data import random_split

class SimCLRDataset(Dataset):
    def __init__(self, root_dir, transform):
        self.root_dir = root_dir
        self.transform = transform
        self.image_paths = [os.path.join(root_dir, img) for img in os.listdir(root_dir)]

    def __getitem__(self, index):
        img_path = self.image_paths[index]
        img = Image.open(img_path).convert('RGB')
        anchor = self.transform(img)
        positive = self.transform(img)
        return anchor, positive

    def __len__(self):
        return len(self.image_paths)

def build_classifier(lr):
    """
        Builds the SimCLR model using YOLO's backbone and a projection head.
        Prepares the DataLoaders for the dataset.

        :param lr: Learning rate for the optimizer.
        :return: Train loader, validation loader, model, loss function, optimizer.
    """

    # --- Step 1: Load YOLO model and add pooling ---
    yolo = YOLO("yolov8n.pt")  # Load YOLOv8 nano model
    # --- Extract Backbone (first 12 layers) ---
    yolo.model.model = yolo.model.model[:11]  # Keep only the first 11 layers 
    
    # --- Dummy Input for Dimension Calculation ---
    dummy = torch.rand(2, 3, 224, 224)  # Simulated input to measure the output dimension
    out = yolo.model.model[:-1](dummy)  # Forward pass without the last layer
    
    # --- Pooling Layer to Ensure Fixed Output Size ---
    class PoolHead(nn.Module):
        def __init__(self, c1):
            super().__init__()
            self.conv = Conv(c1, 1280, 1, 1, None, 1)  # Convolution to match output channels
            self.avgpool = nn.AdaptiveAvgPool2d(1)  # Adaptive Pooling to get 1x1 output
    
        def forward(self, x):
            return self.avgpool(self.conv(x))  # Apply conv and pooling
    
    # --- Replace Last Layer of Backbone with PoolHead ---
    yolo.model.model[-1] = PoolHead(out.shape[1])  # Set PoolHead with correct channels
    
    # --- Flatten Output for Projection Head ---
    out = yolo.model(dummy)
    print(f"Output shape after backbone: {out.shape}")
    
    input_dim = out.flatten(start_dim=1).shape[1]  # Get final flattened output size
    
            
    # --- Step 2: Define SimCLR Model with Projection Head ---
    class SimYOLOv8(nn.Module):
        def __init__(self, backbone, input_dim):
            super(SimYOLOv8, self).__init__()
            self.backbone = backbone
            self.projection_head = SimCLRProjectionHead(
                input_dim=input_dim,
                hidden_dim=2048,
                output_dim=128
            )
    
        def forward(self, x):
            features = self.backbone(x).flatten(start_dim=1)  # Pass through backbone
            projections = self.projection_head(features)  # Pass through SimCLR projection head
            return projections
    
    # --- Step 3: Initialize Model with YOLO Backbone ---
    
    # Enable gradient updates for the YOLO backbone
    backbone = yolo.model.requires_grad_()
    backbone.train()
    
    # Print to verify if gradients are enabled for the backbone
    for param in model.backbone.parameters():
        print(f"Layer {param.shape}: requires_grad = {param.requires_grad}")
        
    model = SimYOLOv8(backbone, input_dim)

    
    # Define the loss function and optimizer
    criterion = InfoNCE(temperature=0.1)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    
    # Define the data transforms
    data_transforms = transforms.Compose([
    transforms.RandomResizedCrop(640),
    transforms.RandomHorizontalFlip(),
    transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.1, hue=0.1),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])
    
    # Replace train_dataset with SimCLRDataset
    
    full_dataset = SimCLRDataset('datasets/cropped/mix_crops', data_transforms)
    dataset_size = len(full_dataset)
    train_size = int(0.7 * dataset_size)
    val_size = int(0.15 * dataset_size)
    test_size = dataset_size - train_size - val_size
    
    train_dataset, val_dataset, test_dataset = random_split(
        full_dataset, [train_size, val_size, test_size]
    )
    
    print(f"Dataset split: {len(train_dataset)} train, {len(val_dataset)} val, {len(test_dataset)} test")
    
    # Create DataLoaders
    train_loader = DataLoader(train_dataset, batch_size=128, shuffle=True, num_workers=4)
    val_loader = DataLoader(val_dataset, batch_size=128, shuffle=False, num_workers=4)
    test_loader = DataLoader(test_dataset, batch_size=128, shuffle=False, num_workers=4)
    return train_loader, val_loader,test_loader, model, criterion, optimizer


    
