#
# MIT License
#
# Copyright (c) 2023 GT4SD team
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
"""Model for Language Modeling."""

import logging
from typing import Any, Dict, Type, Union

import sentencepiece as _sentencepiece
import pytorch_lightning as pl
import torch
import torch.optim as optim
from torch import Tensor
from transformers import (
    AutoConfig,
    AutoModel,
    AutoModelForCausalLM,
    AutoModelForMaskedLM,
    AutoModelForSeq2SeqLM,
    AutoTokenizer,
    XLNetLMHeadModel,
)

# sentencepiece has to be loaded before lightning to avoid segfaults
_sentencepiece

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class BaseLightningModule(pl.LightningModule):
    """Pytorch lightning base model."""

    def __init__(
        self,
        model_args: Dict[str, Any],
    ) -> None:
        """Construct a Pytorch lightning base model.
        Args:
            model_args: model's arguments.
        """
        super().__init__()

        self.model_args = model_args

        self.model: torch.nn.Module

    def forward(self, x: Tensor) -> Tensor:  # type: ignore
        """Forward pass.
        Args:
            x: tensor of shape (batch_size, seq_length) containing the input_ids.
        Returns:
            logits of the model.
        """
        return self.model(x).logits  # type:ignore

    def configure_optimizers(
        self,
    ) -> Dict[str, object]:
        """Create and return the optimizer.
        Returns:
            output (dict of str: Any):
                - optimizer: the optimizer used to update the parameter.
                - ls_scheduler: the scheduler used to reduce the learning rate in every epoch.
                - monitor: the metric that the scheduler will track over the training.
        """

        if not isinstance(self.model_args["lr"], float):
            raise ValueError("Learning rate should be float")

        if not isinstance(self.model_args["lr_decay"], float):
            raise ValueError("Learning rate decay rate should be float")

        optimizer = optim.AdamW(
            self.parameters(),
            lr=self.model_args["lr"],
            weight_decay=self.model_args["weight_decay"],
        )

        scheduler = optim.lr_scheduler.StepLR(optimizer, 1, self.model_args["lr_decay"])

        output = {
            "optimizer": optimizer,
            "lr_scheduler": scheduler,
            "monitor": "val_loss",
        }
        return output

    def training_step(self, batch: Dict[str, Tensor], batch_idx: int) -> Tensor:  # type: ignore
        """
        Training step which encompasses the forward pass and the computation of the loss value.
        Args:
            batch: dictionary containing the input_ids and optionally the token_type_ids and the attention_type.
            batch_idx: index of the current batch, unused.
        Returns:
            loss computed on the batch.
        """
        loss = self.model(**batch).loss  # type:ignore
        self.log("train_loss", loss)
        return loss

    def validation_step(self, batch: Dict[str, Tensor], batch_idx: int) -> Tensor:  # type: ignore
        """
        Validation step which encompasses the forward pass and the computation of the loss value.
        Args:
            batch: dictionary containing the input_ids and optionally the token_type_ids and the attention_type.
            batch_idx: index of the current batch, unused.
        Returns:
            loss computed on the batch.
        """
        loss = self.model(**batch).loss  # type:ignore
        self.log("val_loss", loss)
        return loss


class LMModule(BaseLightningModule):
    """Pytorch lightning model for LM training."""

    def __init__(
        self,
        model_args: Dict[str, Union[float, int, str]],
    ) -> None:
        """Construct an LM lightning module.
        Args:
            model_args: model's arguments.
        """
        super().__init__(model_args)

        self.model: AutoModel
        self.tokenizer: AutoTokenizer

        self.cache_dir = None
        if "cache_dir" in model_args:
            self.cache_dir = model_args["cache_dir"]

        self.init_model()

    def init_model(self) -> None:
        """Initialize an AutoModel."""

        if self.model_args["model_name_or_path"] is not None:
            self.model = AutoModel.from_pretrained(
                self.model_args["model_name_or_path"],
                cache_dir=self.cache_dir,
            )
        else:
            config = AutoConfig.from_pretrained(
                self.model_args["model_config_name"], cache_dir=self.cache_dir
            )

            self.model = AutoModel.from_config(config)

            logger.info("Training from scratch")


class MLMModule(LMModule):
    """Pytorch lightning model for MLM training."""

    def init_model(self) -> None:
        """Initialize a MLM model."""

        if self.model_args["model_name_or_path"] is not None:
            self.model = AutoModelForMaskedLM.from_pretrained(
                self.model_args["model_name_or_path"], cache_dir=self.cache_dir
            )
        else:
            config = AutoConfig.from_pretrained(
                self.model_args["model_config_name"], cache_dir=self.cache_dir
            )

            self.model = AutoModelForMaskedLM.from_config(config)

            logger.info("Training from scratch")

        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_args["tokenizer"], use_fast=False
        )

        self.model.resize_token_embeddings(len(self.tokenizer))  # type: ignore


class CGMModule(LMModule):
    """Pytorch lightning model for conditional generation training."""

    def init_model(self) -> None:
        """Initialize a model for conditional generation."""

        if self.model_args["model_name_or_path"] is not None:
            self.model = AutoModelForSeq2SeqLM.from_pretrained(
                self.model_args["model_name_or_path"],  # type:ignore
                cache_dir=self.cache_dir,
            )
        else:
            config = AutoConfig.from_pretrained(
                self.model_args["model_config_name"], cache_dir=self.cache_dir
            )

            self.model = AutoModelForSeq2SeqLM.from_config(config)

            logger.info("Training from scratch")

        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_args["tokenizer"], use_fast=False
        )

        self.model.resize_token_embeddings(len(self.tokenizer))  # type: ignore


class CLMModule(LMModule):
    """Pytorch lightning model for CLM training."""

    def init_model(self) -> None:
        """Initialize a CLM model."""

        if self.model_args["model_name_or_path"] is not None:
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_args["model_name_or_path"], cache_dir=self.cache_dir
            )
        else:
            config = AutoConfig.from_pretrained(
                self.model_args["model_config_name"], cache_dir=self.cache_dir
            )

            self.model = AutoModelForCausalLM.from_config(config)

            logger.info("Training from scratch")

        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_args["tokenizer"],
            sep_token="<|sep|>",
            pad_token="<|pad|>",
            use_fast=False,
        )

        self.model.resize_token_embeddings(len(self.tokenizer))  # type: ignore


class PLMModule(LMModule):
    """Pytorch lightning model for PLM training."""

    def init_model(self) -> None:
        """Initialize a PLM model."""

        if self.model_args["model_name_or_path"] is not None:
            self.model = XLNetLMHeadModel.from_pretrained(
                self.model_args["model_name_or_path"],  # type:ignore
                cache_dir=self.cache_dir,
            )
        else:
            config = AutoConfig.from_pretrained(
                self.model_args["model_config_name"], cache_dir=self.cache_dir
            )

            self.model = XLNetLMHeadModel.from_config(config)

            logger.info("Training from scratch")

        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_args["tokenizer"], use_fast=False
        )

        self.model.resize_token_embeddings(len(self.tokenizer))  # type: ignore


LM_MODULE_FACTORY: Dict[str, Type[LMModule]] = {
    "lm": LMModule,
    "mlm": MLMModule,
    "clm": CLMModule,
    "cgm": CGMModule,
    "plm": PLMModule,
}
