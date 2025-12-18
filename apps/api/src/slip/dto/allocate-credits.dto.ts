import { Type } from 'class-transformer';
import { ArrayMinSize, IsArray, IsInt, IsString, Min, ValidateNested } from 'class-validator';

class AllocationDto {
  @IsString()
  slipItemId!: string;

  @IsInt()
  @Min(0)
  credits!: number;
}

export class AllocateCreditsDto {
  @IsArray()
  @ArrayMinSize(1)
  @ValidateNested({ each: true })
  @Type(() => AllocationDto)
  allocations!: AllocationDto[];
}
