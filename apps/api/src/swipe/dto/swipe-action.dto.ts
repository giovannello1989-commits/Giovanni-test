import { IsEnum, IsString } from 'class-validator';

export enum SwipeActionType {
  PICK_ONE = 'PICK_ONE',
  PICK_TWO = 'PICK_TWO',
  SKIP = 'SKIP',
}

export class SwipeActionDto {
  @IsString()
  cardId!: string;

  @IsEnum(SwipeActionType)
  action!: SwipeActionType;
}
